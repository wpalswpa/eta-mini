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


def error_locations(response):
    """422 응답에서 오류가 가리키는 위치 목록을 꺼낸다."""
    return [error["loc"] for error in response.json()["detail"]]


# ---------------------------------------------------------------- 정상 응답


# 기대값은 설계서 4절 표에서 손으로 계산한 값이다.
@pytest.mark.parametrize(
    ("distance_km", "pending_orders", "expected_minutes"),
    [
        (2, 5, 26.0),  # 거리와 주문이 뒤바뀌면 29분이라 인자 순서 실수를 잡는다
        (0, 0, 10.0),  # 경계: 규칙이 "0 이상"이라 0은 받아야 한다
        (3, 2, 23.0),  # 교안 15쪽 예시
        (5, 0, 25.0),  # 교안 16쪽 연습문제
        (0, 10, 30.0),  # 교안 16쪽 연습문제
        (20, 0, 70.0),  # 경계: 거리 상한 20km는 받는다
        (0, 1000, 2010.0),  # 큰 값: 주문 수 상한은 아직 없다(설계서 7절 1번)
    ],
)
def test_eta_returns_rule_minutes_and_model_name(client, distance_km, pending_orders, expected_minutes):
    """R3: 정상 요청에 규칙 공식의 예상 시간과 예측기 이름 두 필드만 돌려준다."""
    response = client.post("/eta", json={"distance_km": distance_km, "pending_orders": pending_orders})

    assert response.status_code == 200
    assert response.json() == {"minutes": expected_minutes, "model": "rule"}


def test_eta_ignores_unknown_fields(client):
    """R10: 모르는 필드는 무시하고, 그 필드가 없을 때와 같은 결과를 돌려준다."""
    response = client.post("/eta", json={"distance_km": 1, "pending_orders": 0, "weather": "rain"})

    assert response.status_code == 200
    assert response.json() == {"minutes": 13.0, "model": "rule"}


# ---------------------------------------------------------------- 입력 거절


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
    """R4: 음수·소수 주문·숫자 아닌 값·누락 필드를 422로 거절하고 문제 필드를 가리킨다."""
    response = client.post("/eta", json=body)

    assert response.status_code == 422
    assert ["body", bad_field] in error_locations(response)


# 고치기 전 실측: 거리 "3"은 19분, 거리 true는 13분으로 계산됐다(설계서 8절).
@pytest.mark.parametrize(
    ("body", "bad_field"),
    [
        ({"distance_km": "3", "pending_orders": 0}, "distance_km"),
        ({"distance_km": True, "pending_orders": 0}, "distance_km"),
        ({"distance_km": 1, "pending_orders": "2"}, "pending_orders"),
        ({"distance_km": 1, "pending_orders": True}, "pending_orders"),
        ({"distance_km": 1, "pending_orders": 2.0}, "pending_orders"),  # 값은 정수지만 JSON 형식이 소수
    ],
    ids=["quoted-distance", "bool-distance", "quoted-orders", "bool-orders", "float-form-orders"],
)
def test_eta_rejects_values_of_wrong_json_type(client, body, bad_field):
    """R8: 따옴표 친 숫자·true·소수 형태 주문 수를 숫자로 바꿔 받지 않고 422로 거절한다."""
    response = client.post("/eta", json=body)

    assert response.status_code == 422
    assert ["body", bad_field] in error_locations(response)


@pytest.mark.parametrize("distance_km", [20.000001, 500], ids=["just-over-20km", "500km"])
def test_eta_rejects_distance_over_delivery_limit(client, distance_km):
    """R9: 배달 가능 거리 20km를 넘으면 422로 거절한다(20km 자체는 R3에서 받는다)."""
    response = client.post("/eta", json={"distance_km": distance_km, "pending_orders": 0})

    assert response.status_code == 422
    assert ["body", "distance_km"] in error_locations(response)


# 고치기 전에는 1e309·Infinity가 200과 minutes=null, NaN이 500이었다(설계서 8절).
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
    """R7: 무한대·NaN 거리를 422로 거절하고, 오류 본문이 올바른 JSON이다."""
    # 운영 서버처럼 예외를 500 응답으로 받는다. Infinity·NaN은 json=으로 만들 수 없어 본문을 직접 쓴다.
    client = TestClient(load_app("rule").app, raise_server_exceptions=False)

    response = client.post("/eta", content=body, headers={"content-type": "application/json"})

    assert response.status_code == 422
    assert ["body", "distance_km"] in error_locations(response)


# ---------------------------------------------------------------- 소개 페이지


def test_index_page_returns_html_describing_the_api(client):
    """R14: `/`가 HTML 소개 페이지를 돌려주고, 두 API와 요청 필드, 문서 링크, 지금 예측기 이름을 보여 준다."""
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    page = response.text
    for text in ["POST /eta", "GET /health", "distance_km", "pending_orders", 'href="/docs"']:
        assert text in page
    assert '<code class="model">rule</code>' in page


def test_index_page_shows_predictor_chosen_by_model_impl(load_app, monkeypatch):
    """R14: 소개 페이지의 예측기 이름이 MODEL_IMPL을 따른다."""
    fake_module = types.ModuleType("api.predictors.fake")
    setattr(fake_module, "estimate_delivery_minutes", lambda distance_km, pending_orders: 0.0)
    monkeypatch.setitem(sys.modules, "api.predictors.fake", fake_module)
    client = TestClient(load_app("fake").app)

    assert '<code class="model">fake</code>' in client.get("/").text


def test_index_page_has_no_scripts_or_external_files(client):
    """R14: 소개 페이지는 자바스크립트와 외부 파일 없이 HTML 하나로 끝난다(설계서 2.3)."""
    page = client.get("/").text.lower()

    for banned in ["<script", "<link", " src="]:
        assert banned not in page


def test_index_page_is_not_in_api_schema(client):
    """R14: 소개 페이지는 사람이 읽는 페이지라 API 명세(/openapi.json)에 넣지 않는다."""
    paths = client.get("/openapi.json").json()["paths"]

    assert "/" not in paths
    assert {"/eta", "/health"} <= set(paths)


# ---------------------------------------------------------------- 상태 확인과 예측기 교체


def test_health_reports_status_and_model(client):
    """R5: 상태 확인이 ok와 현재 예측기 이름을 돌려준다."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": "rule"}


def test_model_impl_defaults_to_rule_when_unset(load_app):
    """R6: MODEL_IMPL이 없으면 rule 예측기를 쓴다(교안 16쪽 연습문제 2번)."""
    client = TestClient(load_app(None).app)

    assert client.get("/health").json()["model"] == "rule"


def test_eta_uses_predictor_chosen_by_model_impl(load_app, monkeypatch):
    """R6: MODEL_IMPL로 고른 예측기에 거리·주문 순서로 넘기고, 그 이름을 응답에 싣는다."""
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
    assert calls == [(2.5, 4)]
    assert health.json() == {"status": "ok", "model": "fake"}


def test_model_impl_unknown_name_fails_at_startup(load_app):
    """R6: 없는 예측기 이름이면 요청 시점이 아니라 서버를 띄울 때 실패한다."""
    with pytest.raises(ModuleNotFoundError, match="api.predictors.does_not_exist"):
        load_app("does_not_exist")
