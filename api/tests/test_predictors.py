"""예측기 테스트. 근거: 설계서.md 3절(예측기 교체 규칙), 4절(기준선 공식)."""

import importlib
import math
import pkgutil

import pytest

import api.predictors
from api.predictors.rule import estimate_delivery_minutes

# api/predictors 아래 모든 예측기 모듈 이름. 새 모델 파일을 넣으면 자동으로 계약 검사를 받는다.
PREDICTOR_NAMES = sorted(m.name for m in pkgutil.iter_modules(api.predictors.__path__))


# R1. 기대값은 손으로 계산한 값이다(설계서 4절 표). 테스트 안에서 공식을 다시 계산하지 않는다.
@pytest.mark.parametrize(
    ("distance_km", "pending_orders", "expected_minutes"),
    [
        (0.0, 0, 10.0),  # 거리·대기 주문이 없으면 기본 10분
        (1.0, 0, 13.0),  # 1km당 3분
        (0.0, 1, 12.0),  # 대기 주문 1건당 2분
        (2.5, 3, 23.5),  # 10 + 7.5 + 6
        (12.0, 7, 60.0),  # 10 + 36 + 14
    ],
)
def test_rule_follows_baseline_formula(distance_km, pending_orders, expected_minutes):
    assert estimate_delivery_minutes(distance_km, pending_orders) == pytest.approx(expected_minutes)


def test_predictor_discovery_finds_rule():
    # 자동 탐색이 아무것도 못 찾으면 아래 계약 검사가 0건으로 조용히 통과하므로 먼저 막는다.
    assert "rule" in PREDICTOR_NAMES


# R2. 모든 예측기는 같은 함수 이름·인자 순서를 쓰고, 올바른 입력에 유한한 0 이상 분을 돌려준다.
@pytest.mark.parametrize("name", PREDICTOR_NAMES)
@pytest.mark.parametrize(("distance_km", "pending_orders"), [(0.0, 0), (2.5, 3), (30.0, 50)])
def test_every_predictor_returns_finite_non_negative_minutes(name, distance_km, pending_orders):
    predictor = importlib.import_module(f"api.predictors.{name}")

    minutes = predictor.estimate_delivery_minutes(distance_km, pending_orders)

    assert math.isfinite(minutes)
    assert minutes >= 0
