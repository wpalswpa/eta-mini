# 배달 예상 시간 예측 API

배달 앱 주문 화면에 보여 줄 도착 예정 시간(분)을 돌려주는 API다. 학습 모델 없이 규칙(기본 10분 + 1km당 3분 + 대기 주문 1건당 2분)으로 먼저 배포하고, 뒤에 학습 모델로 바꿔 끼우는 구조를 연습하는 MLOps 실습 저장소다.

## 현재 상태

- 된 것: 규칙 예측기, API 두 개(`POST /eta`, `GET /health`), 계약 테스트, 컨테이너 이미지(빌드, 컨테이너 안 테스트, 서버 응답 확인).
- 안 된 것: CI/CD, 외부 배포, 학습 모델.

## 읽는 순서

1. `README.md`: 실행 방법과 파일 구조.
2. `설계서.md`: API 계약, 예측기 교체 규칙, 검증 결과, 결정 기록의 정본.
3. `AGENTS.md`: AI 도구가 따르는 작업 규칙과 테스트 작성 규칙.

## 실행 방법

필요한 도구: uv, Docker. 예측기는 환경 변수 `MODEL_IMPL`로 고른다(기본 `rule`).

| 하는 일 | 명령 |
|---|---|
| 의존성 설치 | `uv sync --all-groups` |
| 개발 서버 | `uv run uvicorn api.app:app --port 8080 --reload` |
| 테스트 | `uv run pytest -q` |
| 이미지 빌드 | `docker build -f api/Dockerfile -t eta-api .` |
| 컨테이너 안에서 테스트 | `docker run --rm eta-api uv run pytest` |
| 이미지 안 파일 확인 | `docker run --rm eta-api sh -c 'find . \| grep -v .venv'` |
| 컨테이너로 서버 실행 | `docker run --rm --publish 8080:8080 eta-api` |

서버를 띄운 뒤 예상 시간을 요청한다.

```bash
curl -X POST localhost:8080/eta -H 'Content-Type: application/json' -d '{"distance_km": 3, "pending_orders": 2}'
# {"minutes":23.0,"model":"rule"}
```

컨테이너 안 테스트는 실행할 때 개발 의존성(pytest 등)을 내려받으므로 네트워크가 필요하다.

개발 서버가 8080을 쓰는 중에 컨테이너를 `--publish 8080:8080`으로 띄우면, 오류 없이 뜨지만 `localhost:8080` 요청은 모두 개발 서버가 받는다. 컨테이너를 확인하려면 개발 서버를 끄거나 `--publish 8090:8080`처럼 다른 포트로 연결한다. `--publish` 없이 띄우면 서버는 컨테이너 안에서만 열리고 Mac에서는 접속할 수 없다.

## 파일 구조

```text
api/
  app.py               API 정의와 입력 검증
  predictors/rule.py   규칙 예측기(이후 모델이 넘어야 할 기준선)
  tests/               계약 테스트(pytest)
  Dockerfile           컨테이너 이미지 정의
.dockerignore          이미지 빌드에 보내지 않을 파일
pyproject.toml         의존성과 pytest 설정
uv.lock                고정된 의존성 판
설계서.md              계약과 결정의 정본
AGENTS.md              AI 작업 규칙(CLAUDE.md는 이 파일을 불러온다)
```
