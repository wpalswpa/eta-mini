"""예측기 테스트. 근거: 설계서.md 3절(예측기 교체 규칙), 4절(기준선 공식)."""

import importlib
import math
import pkgutil

import pytest

import api.predictors
from api.predictors.rule import estimate_delivery_minutes

# api/predictors 아래 모든 예측기 모듈 이름. 새 모델 파일을 넣으면 자동으로 계약 검사를 받는다.
PREDICTOR_NAMES = sorted(m.name for m in pkgutil.iter_modules(api.predictors.__path__))


# 기대값은 설계서 4절 표에서 손으로 계산한 값이다. 테스트 안에서 공식을 다시 계산하지 않는다.
@pytest.mark.parametrize(
    ("distance_km", "pending_orders", "expected_minutes"),
    [
        (0.0, 0, 10.0),  # 기본 시간
        (1.0, 0, 13.0),  # 1km당 3분
        (0.0, 1, 12.0),  # 대기 주문 1건당 2분
        (2.5, 3, 23.5),  # 10 + 7.5 + 6
        (2.0, 5, 26.0),  # 인자 순서가 바뀌면 29분
        (3.0, 2, 23.0),  # 교안 15쪽 예시
        (5.0, 0, 25.0),  # 교안 16쪽 연습문제
        (0.0, 10, 30.0),  # 교안 16쪽 연습문제
        (12.0, 7, 60.0),  # 10 + 36 + 14
        (20.0, 0, 70.0),  # 거리 상한
        (0.0, 1000, 2010.0),  # 큰 주문 수
    ],
)
def test_rule_follows_baseline_formula(distance_km, pending_orders, expected_minutes):
    """R1: 규칙 예측기가 기본 10분 + 1km당 3분 + 대기 주문 1건당 2분으로 계산한다."""
    assert estimate_delivery_minutes(distance_km, pending_orders) == pytest.approx(expected_minutes)


def test_predictor_discovery_finds_rule():
    """R2 전제: 예측기 자동 탐색이 rule을 찾는다. 못 찾으면 아래 계약 검사가 0건으로 조용히 통과한다."""
    assert "rule" in PREDICTOR_NAMES


@pytest.mark.parametrize("name", PREDICTOR_NAMES)
@pytest.mark.parametrize(("distance_km", "pending_orders"), [(0.0, 0), (2.5, 3), (20.0, 50)])
def test_every_predictor_returns_finite_non_negative_minutes(name, distance_km, pending_orders):
    """R2: 모든 예측기가 같은 함수 이름·인자 순서를 쓰고, 계약 범위 입력에 유한한 0 이상 분을 돌려준다."""
    predictor = importlib.import_module(f"api.predictors.{name}")

    minutes = predictor.estimate_delivery_minutes(distance_km, pending_orders)

    assert math.isfinite(minutes)
    assert minutes >= 0
