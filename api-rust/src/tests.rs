//! 계약 테스트(설계서 2.1, 2.2, 4.7). 가짜 예측기를 써서 ONNX Runtime 없이 돈다.
//! 모델 값 일치는 check_parity 가 맡는다.

use std::sync::{Arc, Mutex};

use axum::body::{to_bytes, Body};
use axum::http::{Request, StatusCode};
use serde_json::{json, Value};
use tower::ServiceExt;

use super::*;

/// 받은 (거리, 주문) 을 기록하고 정해진 값을 돌려준다.
struct Fake {
    calls: Mutex<Vec<(f64, f64)>>,
    result: Result<f64, String>,
}

impl Predictor for Fake {
    fn predict(&self, km: f64, orders: f64) -> Result<f64, String> {
        self.calls.lock().unwrap().push((km, orders));
        self.result.clone()
    }
}

fn state(result: Result<f64, String>) -> (AppState, Arc<Fake>) {
    let fake = Arc::new(Fake { calls: Mutex::new(vec![]), result });
    (AppState { predictor: fake.clone(), model: "rust-onnx".into() }, fake)
}

async fn send(s: AppState, method: &str, path: &str, body: &str) -> (StatusCode, Value) {
    let req = Request::builder().method(method).uri(path).body(Body::from(body.to_string())).unwrap();
    let res = app(s).oneshot(req).await.unwrap();
    let status = res.status();
    let bytes = to_bytes(res.into_body(), usize::MAX).await.unwrap();
    (status, serde_json::from_slice(&bytes).expect("응답 본문은 올바른 JSON 이어야 한다"))
}

#[tokio::test]
async fn eta_returns_minutes_and_model() {
    // 정상 요청: 200, 본문은 minutes 와 model 두 필드뿐
    let (s, _) = state(Ok(28.5));
    let (status, body) = send(s, "POST", "/eta", r#"{"distance_km": 3, "pending_orders": 2}"#).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, json!({"minutes": 28.5, "model": "rust-onnx"}));
}

#[tokio::test]
async fn eta_passes_distance_then_orders() {
    // 인자 순서: 거리 다음 주문 수
    let (s, fake) = state(Ok(1.0));
    send(s, "POST", "/eta", r#"{"distance_km": 2.5, "pending_orders": 7}"#).await;
    assert_eq!(*fake.calls.lock().unwrap(), vec![(2.5, 7.0)]);
}

#[tokio::test]
async fn eta_accepts_boundaries_and_unknown_fields() {
    // 경계(0, 20, 큰 주문 수)와 모르는 필드는 200
    for body in [
        r#"{"distance_km": 0, "pending_orders": 0}"#,
        r#"{"distance_km": 20, "pending_orders": 0}"#,
        r#"{"distance_km": 20.0, "pending_orders": 1000}"#,
        r#"{"distance_km": 3, "pending_orders": 2, "weather": "rain"}"#,
        r#"{"distance_km": 3, "pending_orders": 99999999999999999999}"#,
    ] {
        let (s, _) = state(Ok(1.0));
        assert_eq!(send(s, "POST", "/eta", body).await.0, StatusCode::OK, "{body}");
    }
}

#[tokio::test]
async fn eta_rejects_invalid_input_with_422_and_field_location() {
    // 잘못된 입력은 모두 422 이고 loc 가 문제 필드를 가리킨다(예측기는 부르지 않는다)
    let cases = [
        (r#"{"pending_orders": 2}"#, "distance_km"),
        (r#"{"distance_km": 3}"#, "pending_orders"),
        (r#"{"distance_km": -1, "pending_orders": 2}"#, "distance_km"),
        (r#"{"distance_km": 20.000001, "pending_orders": 2}"#, "distance_km"),
        (r#"{"distance_km": 1e309, "pending_orders": 2}"#, "distance_km"),
        (r#"{"distance_km": "3", "pending_orders": 2}"#, "distance_km"),
        (r#"{"distance_km": true, "pending_orders": 2}"#, "distance_km"),
        (r#"{"distance_km": null, "pending_orders": 2}"#, "distance_km"),
        (r#"{"distance_km": "abc", "pending_orders": 2}"#, "distance_km"),
        (r#"{"distance_km": 3, "pending_orders": -1}"#, "pending_orders"),
        (r#"{"distance_km": 3, "pending_orders": 1.5}"#, "pending_orders"),
        (r#"{"distance_km": 3, "pending_orders": 2.0}"#, "pending_orders"),
        (r#"{"distance_km": 3, "pending_orders": 2e0}"#, "pending_orders"),
        (r#"{"distance_km": 3, "pending_orders": "2"}"#, "pending_orders"),
        (r#"{"distance_km": 3, "pending_orders": true}"#, "pending_orders"),
    ];
    for (body, field) in cases {
        let (s, fake) = state(Ok(1.0));
        let (status, out) = send(s, "POST", "/eta", body).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
        assert_eq!(out["detail"][0]["loc"], json!(["body", field]), "{body}");
        assert!(fake.calls.lock().unwrap().is_empty(), "{body}");
    }
}

#[tokio::test]
async fn eta_reports_both_field_errors() {
    // 두 필드가 모두 틀리면 오류 두 개
    let (s, _) = state(Ok(1.0));
    let (status, out) = send(s, "POST", "/eta", r#"{"distance_km": -1, "pending_orders": "x"}"#).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(out["detail"].as_array().unwrap().len(), 2);
}

#[tokio::test]
async fn eta_writes_infinite_input_as_string() {
    // 무한대 입력값은 오류 본문에서 "inf" 문자열이다(표준 JSON 은 무한대를 쓸 수 없다)
    let (s, _) = state(Ok(1.0));
    let (status, out) = send(s, "POST", "/eta", r#"{"distance_km": 1e309, "pending_orders": 2}"#).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(out["detail"][0]["input"], json!("inf"));
}

#[tokio::test]
async fn eta_rejects_malformed_body_with_422() {
    // 400·415 가 아니라 모두 422(JSON 이 아니거나 객체가 아님, NaN·Infinity 글자)
    for body in [
        "",
        "not json",
        "[1, 2]",
        "3",
        r#""x""#,
        "null",
        r#"{"distance_km": NaN, "pending_orders": 1}"#,
        r#"{"distance_km": Infinity, "pending_orders": 1}"#,
    ] {
        let (s, _) = state(Ok(1.0));
        let (status, out) = send(s, "POST", "/eta", body).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
        assert_eq!(out["detail"][0]["loc"][0], json!("body"), "{body}");
    }
}

#[tokio::test]
async fn eta_ignores_content_type() {
    // Content-Type 이 없거나 text/plain 이어도 415 가 아니라 본문 내용으로 판정한다
    let (s, _) = state(Ok(1.0));
    let req = Request::builder()
        .method("POST")
        .uri("/eta")
        .header("content-type", "text/plain")
        .body(Body::from(r#"{"distance_km": 3, "pending_orders": 2}"#))
        .unwrap();
    assert_eq!(app(s).oneshot(req).await.unwrap().status(), StatusCode::OK);
}

#[tokio::test]
async fn eta_predictor_failure_or_non_finite_is_500() {
    // 예측 실패와 유한하지 않은 결과는 500 이다(minutes 가 null 로 나가지 않게)
    for result in [Err("실패".to_string()), Ok(f64::NAN), Ok(f64::INFINITY)] {
        let (s, _) = state(result);
        let (status, out) = send(s, "POST", "/eta", r#"{"distance_km": 1, "pending_orders": 1}"#).await;
        assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
        assert_eq!(out, json!({"detail": "Internal Server Error"}));
    }
}

#[tokio::test]
async fn health_reports_status_and_model() {
    // GET /health: 200, 상태와 예측기 이름
    let (s, _) = state(Ok(1.0));
    let (status, out) = send(s, "GET", "/health", "").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(out, json!({"status": "ok", "model": "rust-onnx"}));
}

#[tokio::test]
async fn unknown_path_is_404_and_wrong_method_is_405() {
    // 없는 주소 404, 있는 주소에 다른 방법 405. 본문은 {"detail": ...}
    for (method, path, want) in [
        ("GET", "/nope", StatusCode::NOT_FOUND),
        ("GET", "/", StatusCode::NOT_FOUND),
        ("GET", "/eta", StatusCode::METHOD_NOT_ALLOWED),
        ("POST", "/health", StatusCode::METHOD_NOT_ALLOWED),
    ] {
        let (s, _) = state(Ok(1.0));
        let (status, out) = send(s, method, path, "").await;
        assert_eq!(status, want, "{method} {path}");
        assert!(out["detail"].is_string(), "{method} {path}");
    }
}

#[test]
fn integer_token_follows_json_integer_grammar() {
    // 정수 글자: 소수점·지수·앞자리 0 은 정수가 아니다
    for ok in ["0", "7", "-3", "10", "99999999999999999999"] {
        assert!(validate::is_integer_token(ok), "{ok}");
    }
    for bad in ["", "-", "1.0", "1e2", "01", "+1"] {
        assert!(!validate::is_integer_token(bad), "{bad}");
    }
}
