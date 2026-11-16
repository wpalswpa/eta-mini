# 배달 예상 시간 예측 API

배달 앱 주문 화면에 보여 줄 도착 예정 시간(분)을 돌려주는 API다. 학습 모델 없이 규칙(기본 10분 + 1km당 3분 + 대기 주문 1건당 2분)으로 먼저 배포하고, 뒤에 학습 모델로 바꿔 끼우는 구조를 연습하는 MLOps 실습 저장소다.

## 현재 상태

- 된 것: 규칙 예측기(`rule`), scikit-learn 예측기(`sklearn`), API 두 개(`POST /eta`, `GET /health`), 서버 주소(`/`)의 소개 페이지, 계약 테스트, 모델 학습 파이프라인(`training/data.py`, `training/train_sklearn.py`), 검증 게이트(`training/validate_model.py`), 컨테이너 이미지(빌드, 컨테이너 안 테스트, 서버 응답 확인), GitHub Actions 자동 테스트 및 Render CD 연동 배포 정의(`.github/workflows/ci.yml`), Render 배포(https://eta-api-fcvw.onrender.com).
- 안 된 것: 딥러닝 구현체(`dl`), ONNX 변환 및 Go/Rust 서빙, 운영 지표 모니터링.

## 읽는 순서

1. `README.md`: 실행 방법과 파일 구조.
2. `설계서.md`: API 계약, 예측기 교체 규칙, 검증 결과, 결정 기록의 정본.
3. `AGENTS.md`: AI 도구가 따르는 작업 규칙과 테스트 작성 규칙.

## 실행 방법

필요한 도구: uv, Docker. 예측기는 환경 변수 `MODEL_IMPL`로 고른다(기본 `rule`).

| 하는 일 | 명령 |
|---|---|
| 의존성 설치 | `uv sync --all-groups` |
| scikit-learn 모델 학습 | `uv run python -m training.train_sklearn` |
| 모델 검증 게이트 | `uv run python -m training.validate_model sklearn` |
| PyTorch 모델 학습(train 그룹, CPU 전용 torch) | `uv run --group train python -m training.train_dl` |
| PyTorch 모델 검증 게이트 | `uv run --group train python -m training.validate_model dl` |
| 테스트(dl 포함) | `uv run --group train pytest -q` |
| 개발 서버 (규칙 예측기) | `uv run uvicorn api.app:app --port 8080 --reload` |
| 개발 서버 (sklearn 예측기) | `MODEL_IMPL=sklearn uv run uvicorn api.app:app --port 8081 --reload` |
| 테스트 | `uv run pytest -q` |
| CI와 같은 테스트(잠금 파일 확인 포함) | `uv run --locked pytest -q` |
| 이미지 빌드 | `docker build -f api/Dockerfile -t eta-api .` |
| 컨테이너 안에서 테스트 | `docker run --rm eta-api uv run pytest` |
| 이미지 안 파일 확인 | `docker run --rm eta-api sh -c 'find . \| grep -v .venv'` |
| 컨테이너로 서버 실행 | `docker run --rm --publish 8080:8080 eta-api` |
| Go 서비스 이미지 빌드(먼저 학습·ONNX 변환) | `docker build -f api-go/Dockerfile -t eta-api-go .` |
| Go 서비스 실행 | `docker run --rm --publish 8081:8080 eta-api-go` |
| Go 서비스만 예측 일치 비교 | `TARGETS=go=http://127.0.0.1:8081 uv run python -m training.check_parity` |
| Rust 서비스 이미지 빌드(먼저 학습·ONNX 변환) | `docker build -f api-rust/Dockerfile -t eta-api-rust .` |
| Rust 서비스 실행 | `docker run --rm --publish 8082:8080 eta-api-rust` |
| Python API와 예측 일치 비교(Python API는 `MODEL_IMPL=sklearn`, 8080) | `uv run python -m training.check_parity` |

서버를 띄운 뒤 예상 시간을 요청한다.

```bash
# 규칙 예측기 (8080 포트): 기본 10 + 3*3 + 2*2 = 23.0분
curl -X POST localhost:8080/eta -H 'Content-Type: application/json' -d '{"distance_km": 3, "pending_orders": 2}'
# {"minutes":23.0,"model":"rule"}

# sklearn 모델 예측기 (8081 포트): 실제 배달 공식에 근접한 약 28.94분
curl -X POST localhost:8081/eta -H 'Content-Type: application/json' -d '{"distance_km": 3, "pending_orders": 2}'
# {"minutes":28.94072198442544,"model":"sklearn"}
```

컨테이너 안 테스트는 실행할 때 개발 의존성(pytest 등)을 내려받으므로 네트워크가 필요하다.

개발 서버가 8080을 쓰는 중에 컨테이너를 `--publish 8080:8080`으로 띄우면, 오류 없이 뜨지만 `localhost:8080` 요청은 모두 개발 서버가 받는다. 컨테이너를 확인하려면 개발 서버를 끄거나 `--publish 8090:8080`처럼 다른 포트로 연결한다. `--publish` 없이 띄우면 서버는 컨테이너 안에서만 열리고 Mac에서는 접속할 수 없다.

GitHub에 올리면 `.github/workflows/ci.yml`이 테스트를 돌린다. PR을 열거나 `main`에 push할 때 돌고, 다른 브랜치를 push만 해서는 돌지 않는다. `v`로 시작하는 태그를 push하면 테스트 뒤 이미지를 `ghcr.io/wpalswpa/eta-mini/eta-api`에 올린다.

## 파일 구조

```text
.github/workflows/ci.yml  GitHub Actions 테스트, 이미지 빌드 및 Render CD 배포
api/
  app.py                  API 정의와 입력 검증
  index.html              서버 주소(`/`)의 소개 페이지
  predictors/
    rule.py               규칙 기반 예측기 (기준선 baseline)
    sklearn.py            scikit-learn 기반 학습 모델 예측기
    dl.py                 PyTorch 기반 학습 모델 예측기(torch는 train 그룹)
  tests/                  계약 테스트 (pytest)
  Dockerfile              컨테이너 이미지 정의
api-go/                   Go 서비스(ONNX Runtime): 같은 API 계약, ONNX 모델 서빙. Dockerfile 포함
api-rust/                 Rust 서비스(axum, ort): 같은 API 계약, ONNX 모델 서빙. Dockerfile 포함
training/
  data.py                 재현 가능한 배달 데이터 생성 (collect_data)
  train_sklearn.py        scikit-learn 회귀 모델 학습 파이프라인
  train_dl.py             PyTorch 회귀 모델 학습(하이퍼파라미터를 지표 파일에 기록)
  validate_model.py       모델 검증 게이트 (기준선 비교 및 절대 상한 검증)
artifacts/                학습 산출물 (joblib 모델, 메트릭 json - .gitignore)
.dockerignore             이미지 빌드에 보내지 않을 파일
pyproject.toml            의존성과 pytest 설정
uv.lock                   고정된 의존성 판
설계서.md                 계약과 결정의 정본
AGENTS.md                 AI 작업 규칙(CLAUDE.md는 이 파일을 불러온다)
```
