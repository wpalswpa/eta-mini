import numpy as np


def collect_data(n: int = 500, seed: int = 0):
    """배달 기록을 수집한다 (여기서는 생성).

    같은 seed 면 항상 같은 데이터가 나온다. 학습 재현성의 출발점이다.

    Args:
        n: 배달 건수.
        seed: 난수 시드.

    Returns:
        (X, y) 튜플. X 는 [n, 2] (배달 거리 km, 대기 주문 수), y 는 [n] 실제 걸린 시간(분). 모두 float32.
    """
    rng = np.random.default_rng(seed)
    distance_km = rng.uniform(0.5, 8.0, n)
    pending_orders = rng.integers(0, 11, n).astype(float)
    noise = rng.normal(0, 1.5, n)
    minutes = 12.0 + 3.0 * distance_km + 4.0 * pending_orders + noise
    X = np.column_stack([distance_km, pending_orders]).astype(np.float32)
    y = minutes.astype(np.float32)
    return X, y
