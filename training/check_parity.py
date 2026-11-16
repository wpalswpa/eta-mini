"""Python API 와 다른 언어 서비스(Go, Rust)의 예측이 같은지 비교한다.
기준은 Python API(PY_URL), 학습한 원본 모델(MODEL_IMPL=sklearn)로 띄운 것이다.
서버가 떠 있어야 해서 pytest 가 아니라 따로 실행한다. 하나라도 FAIL 이면 종료 코드 1.
    uv run python -m training.check_parity
환경 변수: PY_URL(기본 http://127.0.0.1:8080), TARGETS(기본 go=http://127.0.0.1:8081,rust=http://127.0.0.1:8082)
"""

import json
import os
import random
import sys
import urllib.request

TOLERANCE = 1e-4  # 분

PY_URL = os.environ.get("PY_URL", "http://127.0.0.1:8080")
TARGETS = dict(
    item.split("=", 1)
    for item in os.environ.get("TARGETS", "go=http://127.0.0.1:8081,rust=http://127.0.0.1:8082").split(",")
    if item
)


def make_inputs() -> list[tuple[float, int]]:
    """고정 3건 + seed 0 무작위 20건 (거리 0.5~8km, 주문 0~10건)."""
    rng = random.Random(0)
    fixed = [(3.0, 2), (0.0, 0), (8.0, 10)]
    return fixed + [(rng.uniform(0.5, 8.0), rng.randint(0, 10)) for _ in range(20)]


def predict(base_url: str, km: float, orders: int) -> float:
    body = json.dumps({"distance_km": km, "pending_orders": orders}).encode()
    req = urllib.request.Request(base_url.rstrip("/") + "/eta", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as res:
        return float(json.load(res)["minutes"])


def main() -> int:
    inputs = make_inputs()
    try:
        want = [predict(PY_URL, km, n) for km, n in inputs]
    except Exception as e:  # 기준이 없으면 비교할 수 없다
        print(f"FAIL 기준 서버(PY_URL={PY_URL}) 호출 실패: {e}")
        return 1

    ok = True
    for name, url in TARGETS.items():
        try:
            got = [predict(url, km, n) for km, n in inputs]
            diff = max(abs(g - w) for g, w in zip(got, want))
            passed = diff < TOLERANCE
            print(f"{'PASS' if passed else 'FAIL'} [{name}] {len(inputs)}건 최대 오차 {diff:.2e}분 (기준 {TOLERANCE:.0e}분 미만)")
        except Exception as e:  # 연결 실패, 응답 형식 오류도 FAIL
            passed = False
            print(f"FAIL [{name}] 호출 실패: {e}")
        ok &= passed
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
