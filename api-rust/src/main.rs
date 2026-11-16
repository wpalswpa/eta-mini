//! Python API(api/app.py)와 같은 계약(설계서 2.1, 2.2)을 지키는 Rust 서비스. 설계서 4.7.
//!
//! axum 의 Json 추출기는 형식 오류에 400·415 를 돌려주므로 쓰지 않고, 본문을 직접 파싱해
//! 모든 입력 오류를 422 로 맞춘다.

mod predictor;
mod validate;

use std::path::PathBuf;
use std::sync::Arc;

use axum::body::{to_bytes, Body};
use axum::extract::State;
use axum::http::{Request, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde_json::json;

use predictor::{OnnxPredictor, Predictor};

const MAX_BODY_BYTES: usize = 1 << 20;

#[derive(Clone)]
struct AppState {
    predictor: Arc<dyn Predictor>,
    model: Arc<str>, // 응답의 model 값(장애 추적용)
}

fn detail(status: StatusCode, text: &str) -> Response {
    (status, Json(json!({ "detail": text }))).into_response()
}

async fn health(State(s): State<AppState>) -> Response {
    Json(json!({"status": "ok", "model": &*s.model})).into_response()
}

async fn eta(State(s): State<AppState>, req: Request<Body>) -> Response {
    let Ok(body) = to_bytes(req.into_body(), MAX_BODY_BYTES).await else {
        return detail(StatusCode::PAYLOAD_TOO_LARGE, "Request Entity Too Large");
    };
    let input = match validate::parse_eta_request(&body) {
        Ok(input) => input,
        Err(errs) => return (StatusCode::UNPROCESSABLE_ENTITY, Json(json!({ "detail": errs }))).into_response(),
    };
    match s.predictor.predict(input.distance_km, input.pending_orders) {
        Ok(minutes) if minutes.is_finite() => Json(json!({"minutes": minutes, "model": &*s.model})).into_response(),
        other => {
            eprintln!("예측 실패: {other:?}");
            detail(StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error")
        }
    }
}

async fn not_found() -> Response {
    detail(StatusCode::NOT_FOUND, "Not Found")
}

async fn method_not_allowed() -> Response {
    detail(StatusCode::METHOD_NOT_ALLOWED, "Method Not Allowed")
}

/// 없는 주소는 404, 있는 주소에 다른 방법이면 405. 본문은 FastAPI 와 같은 {"detail": ...}
fn app(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health).fallback(method_not_allowed))
        .route("/eta", post(eta).fallback(method_not_allowed))
        .fallback(not_found)
        .with_state(state)
}

fn getenv(key: &str, fallback: &str) -> String {
    std::env::var(key).ok().filter(|v| !v.is_empty()).unwrap_or_else(|| fallback.to_string())
}

#[tokio::main]
async fn main() {
    let model_path = PathBuf::from(getenv("MODEL_DIR", "artifacts")).join("model_sklearn.onnx");
    let lib_path = getenv("ORT_LIB", "/opt/onnxruntime/lib/libonnxruntime.so");
    // 모델이 없으면 시작하지 못한다(설계서 3절과 같은 이유)
    let predictor = OnnxPredictor::load(&lib_path, &model_path).unwrap_or_else(|e| {
        eprintln!("{e}");
        std::process::exit(1);
    });
    let state = AppState { predictor: Arc::new(predictor), model: getenv("MODEL_IMPL", "rust-onnx").into() };
    let addr = format!("0.0.0.0:{}", getenv("PORT", "8080"));
    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap_or_else(|e| {
        eprintln!("{addr} 을 열지 못함: {e}");
        std::process::exit(1);
    });
    println!("듣는 중 {addr} (model={})", state.model);
    axum::serve(listener, app(state)).await.expect("서버 오류");
}

#[cfg(test)]
mod tests;
