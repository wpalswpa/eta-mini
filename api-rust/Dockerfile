# 빌드 컨텍스트는 저장소 루트다: docker build -f api-rust/Dockerfile -t eta-api-rust .
# 먼저 학습·변환으로 artifacts/model_sklearn.onnx 를 만들어 둔다(README 참고).
FROM rust:1-bookworm AS build
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

# 의존성 크레이트를 먼저 받아 두면 소스만 바뀔 때 다시 받지 않는다
COPY api-rust/Cargo.toml api-rust/Cargo.lock ./
RUN mkdir src && echo 'fn main() {}' > src/main.rs && cargo build --release --locked && rm -rf src
COPY api-rust/src ./src
RUN touch src/main.rs && cargo build --release --locked

FROM debian:bookworm-slim
WORKDIR /app
COPY --from=build /opt/onnxruntime/lib /opt/onnxruntime/lib
COPY --from=build /src/target/release/eta-api-rust /app/eta-api-rust
COPY artifacts/model_sklearn.onnx /app/artifacts/model_sklearn.onnx
ENV ORT_LIB=/opt/onnxruntime/lib/libonnxruntime.so \
    MODEL_DIR=/app/artifacts \
    PORT=8080
EXPOSE 8080
CMD ["/app/eta-api-rust"]
