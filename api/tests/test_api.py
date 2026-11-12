"""API 계약 테스트. 근거: 설계서.md 2절(API 계약), 3절(예측기 교체 규칙)."""

import importlib
import sys
import types

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def load_app(monkeypatch):
    """MODEL_IMPL을 정한 뒤 api.app을 새로 불러오는 함수를 준다.

    api.app은 불러올 때 한 번만 MODEL_IMPL을 읽는다. 그래서 테스트마다 새로 불러온다.
    model_impl=None이면 환경 변수를 지워 기본값을 확인한다.
    테스트가 끝나면 환경 변수와 원래 api.app 모듈을 되돌린다.
    """
    original = sys.modules.pop("api.app", None)

    def _load(model_impl: str | None = "rule"):
        if model_impl is None:
            monkeypatch.delenv("MODEL_IMPL", raising=False)
        else:
            monkeypatch.setenv("MODEL_IMPL", model_impl)
        sys.modules.pop("api.app", None)
        return importlib.import_module("api.app")

    yield _load

    sys.modules.pop("api.app", None)
    if original is not None:
        sys.modules["api.app"] = original


@pytest.fixture
def client(load_app):
    return TestClient(load_app("rule").app)


# R3. 2km·5건은 인자 순서가 바르면 26분, 거리와 주문이 뒤바뀌면 29분이라 순서 실수를 잡는다.
@pytest.mark.parametrize(
    ("distance_km", "pending_orders", "expected_minutes"),
    [
        (2, 5, 26.0),
        (0, 0, 10.0),  # 경계: 규칙이 "0 이상"이라 0은 받아야 한다
    ],
)
def test_eta_returns_rule_minutes_and_model_name(client, distance_km, pending_orders, expected_minutes):
    response = client.post("/eta", json={"distance_km": distance_km, "pending_orders": pending_orders})

    assert response.status_code == 200
    assert response.json() == {"minutes": expected_minutes, "model": "rule"}


# R4. 잘못된 입력은 422로 거절하고, 오류 위치가 문제 필드를 가리켜야 한다.
@pytest.mark.parametrize(
    ("body", "bad_field"),
    [
        ({"distance_km": -0.1, "pending_orders": 0}, "distance_km"),
        ({"distance_km": 1, "pending_orders": -1}, "pending_orders"),
        ({"distance_km": 1, "pending_orders": 1.5}, "pending_orders"),
        ({"distance_km": "far", "pending_orders": 0}, "distance_km"),
        ({"distance_km": 1}, "pending_orders"),
    ],
    # 한글 ID는 pytest 출력에서 \uXXXX로 깨져 보여 영문으로 쓴다.
    ids=["negative-distance", "negative-orders", "fractional-orders", "string-distance", "missing-orders"],
)
def test_eta_rejects_invalid_input(client, body, bad_field):
    response = client.post("/eta", json=body)

    assert response.status_code == 422
    assert ["body", bad_field] in [error["loc"] for error in response.json()["detail"]]


# R7. 무한대·NaN 거리는 422로 거절하고, 오류 본문은 올바른 JSON이어야 한다(설계서 2.1, 7절).
# 고치기 전에는 1e309·Infinity가 200과 minutes=null, NaN이 500이었다.
@pytest.mark.parametrize(
    "body",
    [
        '{"distance_km": 1e309, "pending_orders": 0}',  # 표준 JSON 숫자지만 Python에서 무한대
        '{"distance_km": Infinity, "pending_orders": 0}',
        '{"distance_km": NaN, "pending_orders": 0}',
        '{"distance_km": NaN}',  # 주문 누락 오류가 본문 전체를 input에 담으므로 안쪽 NaN까지 바꿔야 한다
    ],
    ids=["overflow", "infinity", "nan", "nan-with-missing-orders"],
)
def test_eta_rejects_non_finite_distance(load_app, body):
    # 운영 서버처럼 예외를 500 응답으로 받는다. Infinity·NaN은 json=으로 만들 수 없어 본문을 직접 쓴다.
    client = TestClient(load_app("rule").app, raise_server_exceptions=False)

    response = client.post("/eta", content=body, headers={"content-type": "application/json"})

    assert response.status_code == 422
    assert ["body", "distance_km"] in [error["loc"] for error in response.json()["detail"]]


# R5
def test_health_reports_status_and_model(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": "rule"}


# R6. MODEL_IMPL 교체 규칙
def test_model_impl_defaults_to_rule_when_unset(load_app):
    client = TestClient(load_app(None).app)

    assert client.get("/health").json()["model"] == "rule"


def test_eta_uses_predictor_chosen_by_model_impl(load_app, monkeypatch):
    calls = []

    def fake_estimate(distance_km, pending_orders):
        calls.append((distance_km, pending_orders))
        return 42.0

    # 저장소에 테스트용 예측기 파일을 두지 않고, 이 테스트 동안만 모듈 목록에 넣는다.
    fake_module = types.ModuleType("api.predictors.fake")
    setattr(fake_module, "estimate_delivery_minutes", fake_estimate)
    monkeypatch.setitem(sys.modules, "api.predictors.fake", fake_module)
    client = TestClient(load_app("fake").app)

    eta = client.post("/eta", json={"distance_km": 2.5, "pending_orders": 4})
    health = client.get("/health")

    assert eta.json() == {"minutes": 42.0, "model": "fake"}
    assert calls == [(2.5, 4)]  # 거리, 대기 주문 순서로 넘겨야 한다
    assert health.json() == {"status": "ok", "model": "fake"}


def test_model_impl_unknown_name_fails_at_startup(load_app):
    # 잘못된 설정은 요청 시점이 아니라 서버를 띄울 때 드러나야 한다.
    with pytest.raises(ModuleNotFoundError, match="api.predictors.does_not_exist"):
        load_app("does_not_exist")
