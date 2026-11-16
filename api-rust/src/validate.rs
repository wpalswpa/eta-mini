//! 설계서 2.1 의 입력 검증. pydantic(strict=True) 과 같은 판정을 JSON 글자 그대로 본다. 설계서 4.7.

use serde_json::{json, Value};

const MAX_DISTANCE_KM: f64 = 20.0;

/// FastAPI 기본 422 본문의 detail 항목과 같은 모양이다.
pub type FieldError = Value;

#[derive(Debug, PartialEq)]
pub struct EtaInput {
    pub distance_km: f64,
    pub pending_orders: f64, // 정수 글자만 받는다. 모델 입력이 실수라 실수로 들고 있다
}

fn error(typ: &str, loc: Value, msg: &str, input: Value) -> FieldError {
    json!({"type": typ, "loc": loc, "msg": msg, "input": input})
}

/// 본문을 검사해 입력을 돌려주거나, 422 로 돌려줄 오류 목록을 돌려준다.
pub fn parse_eta_request(body: &[u8]) -> Result<EtaInput, Vec<FieldError>> {
    // NaN, Infinity 글자도 JSON 문법 오류라 여기서 거절한다
    let Ok(whole) = serde_json::from_slice::<Value>(body) else {
        return Err(vec![error("json_invalid", json!(["body", 0]), "JSON decode error", json!({}))]);
    };
    let Value::Object(fields) = &whole else {
        return Err(vec![error(
            "model_attributes_type",
            json!(["body"]),
            "Input should be a valid dictionary or object to extract fields from",
            whole,
        )]);
    };

    let mut errs = Vec::new();
    let mut distance = 0.0;
    let mut orders = 0.0;

    match fields.get("distance_km") {
        None => errs.push(error("missing", json!(["body", "distance_km"]), "Field required", whole.clone())),
        Some(raw) => match check_distance(raw) {
            Ok(v) => distance = v,
            Err(e) => errs.push(e),
        },
    }
    match fields.get("pending_orders") {
        None => errs.push(error("missing", json!(["body", "pending_orders"]), "Field required", whole.clone())),
        Some(raw) => match check_orders(raw) {
            Ok(v) => orders = v,
            Err(e) => errs.push(e),
        },
    }

    if errs.is_empty() {
        Ok(EtaInput { distance_km: distance, pending_orders: orders })
    } else {
        Err(errs)
    }
}

fn check_distance(raw: &Value) -> Result<f64, FieldError> {
    let loc = json!(["body", "distance_km"]);
    // 따옴표 친 숫자, true/false, null, 객체 등은 숫자가 아니다
    let Value::Number(n) = raw else {
        return Err(error("float_type", loc, "Input should be a valid number", raw.clone()));
    };
    let v: f64 = n.to_string().parse().unwrap_or(f64::NAN);
    if !v.is_finite() {
        // 1e309 처럼 무한대가 되는 값
        return Err(error("finite_number", loc, "Input should be a finite number", json_safe(v)));
    }
    if v < 0.0 {
        return Err(error("greater_than_equal", loc, "Input should be greater than or equal to 0", raw.clone()));
    }
    if v > MAX_DISTANCE_KM {
        return Err(error("less_than_equal", loc, "Input should be less than or equal to 20", raw.clone()));
    }
    Ok(v)
}

fn check_orders(raw: &Value) -> Result<f64, FieldError> {
    let loc = json!(["body", "pending_orders"]);
    // 소수점·지수가 있는 값(2.0 포함), 문자열, true/false, null 은 정수가 아니다
    let token = match raw {
        Value::Number(n) if is_integer_token(&n.to_string()) => n.to_string(),
        _ => return Err(error("int_type", loc, "Input should be a valid integer", raw.clone())),
    };
    let v: f64 = token.parse().unwrap_or(f64::NAN);
    if v < 0.0 {
        return Err(error("greater_than_equal", loc, "Input should be greater than or equal to 0", raw.clone()));
    }
    Ok(v)
}

/// `-?(0|[1-9][0-9]*)` 와 같다.
pub(crate) fn is_integer_token(tok: &str) -> bool {
    let digits = tok.strip_prefix('-').unwrap_or(tok);
    !digits.is_empty()
        && digits.bytes().all(|b| b.is_ascii_digit())
        && (digits == "0" || !digits.starts_with('0'))
}

/// JSON 으로 쓸 수 없는 무한대·NaN 을 문자열로 바꾼다(설계서 2.1 마지막 항목).
fn json_safe(v: f64) -> Value {
    if v.is_nan() {
        json!("nan")
    } else if v == f64::INFINITY {
        json!("inf")
    } else if v == f64::NEG_INFINITY {
        json!("-inf")
    } else {
        json!(v)
    }
}
