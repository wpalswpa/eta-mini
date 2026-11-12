import importlib
import math
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

MODEL_IMPL = os.getenv("MODEL_IMPL", "rule")
estimate_delivery_minutes = importlib.import_module(f"api.predictors.{MODEL_IMPL}").estimate_delivery_minutes

class EtaRequest(BaseModel):
    """배달 예상 시간 요청"""
    # 모델이 더 많은 정보를 원하면 여기에 필드를 추가
    # allow_inf_nan=False: 1e309처럼 무한대가 되는 값을 받으면 minutes가 null로 나간다
    distance_km: float = Field(ge=0, allow_inf_nan=False, description="가게에서 배달지까지 거리(km)")
    pending_orders: int = Field(ge=0, description="지금 밀려 있는 주문 수")

class EtaResponse(BaseModel):
    """배달 예상 시간 응답"""
    minutes: float
    model: str  # 어떤 구현체가 낸 예측인지 (장애 추적용)

app = FastAPI(title="delivery-eta")

def _json_safe(value: Any) -> Any:
    """JSON으로 표현할 수 없는 무한대·NaN 실수를 문자열로 바꾼다. 딕셔너리·리스트 안쪽까지 본다."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)  # "inf", "-inf", "nan"
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value

@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI 기본 422 응답과 같은 형식으로 돌려주되, 입력값의 무한대·NaN은 문자열로 바꾼다.

    기본 처리기는 오류에 담긴 입력값을 그대로 JSON으로 만들다가 무한대·NaN에서 500을 낸다.
    """
    return JSONResponse(status_code=422, content={"detail": _json_safe(jsonable_encoder(exc.errors()))})

@app.get("/health")
def health() -> dict[str, str]:
    """서비스 상태와 현재 구현체 이름을 돌려준다."""
    return {"status": "ok", "model": MODEL_IMPL}

@app.post("/eta", response_model=EtaResponse)
def eta(req: EtaRequest) -> EtaResponse:
    """배달 예상 시간을 계산"""
    minutes = estimate_delivery_minutes(req.distance_km, req.pending_orders)
    return EtaResponse(minutes=minutes, model=MODEL_IMPL)

