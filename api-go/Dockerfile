# 빌드 컨텍스트는 저장소 루트다: docker build -f api-go/Dockerfile -t eta-api-go .
# 먼저 학습·변환으로 artifacts/model_sklearn.onnx 를 만들어 둔다(README 참고).
FROM golang:1.25-bookworm AS build
ARG TARGETARCH
WORKDIR /src

# ONNX Runtime 판은 uv.lock 의 onnxruntime 판을 읽어 쓴다(숫자를 적지 않는다). 파일은 TARGETARCH 에 맞춘다.
COPY uv.lock /tmp/uv.lock
RUN set -eu; \
    ORT_VERSION="$(awk '/^name = "onnxruntime"$/ {getline; gsub(/version = |"/, ""); print; exit}' /tmp/uv.lock)"; \
    test -n "$ORT_VERSION"; \
    case "$TARGETARCH" in amd64) ORT_ARCH=x64 ;; arm64) ORT_ARCH=aarch64 ;; *) echo "지원하지 않는 TARGETARCH: $TARGETARCH" >&2; exit 1 ;; esac; \
    NAME="onnxruntime-linux-${ORT_ARCH}-${ORT_VERSION}"; \
    curl -fsSL "https://github.com/microsoft/onnxruntime/releases/download/v${ORT_VERSION}/${NAME}.tgz" | tar -xz -C /opt; \
    mv "/opt/${NAME}" /opt/onnxruntime

COPY api-go/go.mod api-go/go.sum ./
RUN go mod download
COPY api-go/*.go ./
RUN CGO_ENABLED=1 go build -o /eta-api-go .

FROM debian:bookworm-slim
WORKDIR /app
COPY --from=build /opt/onnxruntime/lib /opt/onnxruntime/lib
COPY --from=build /eta-api-go /app/eta-api-go
COPY artifacts/model_sklearn.onnx /app/artifacts/model_sklearn.onnx
ENV ONNXRUNTIME_LIB=/opt/onnxruntime/lib/libonnxruntime.so \
    MODEL_DIR=/app/artifacts \
    PORT=8080
EXPOSE 8080
CMD ["/app/eta-api-go"]
