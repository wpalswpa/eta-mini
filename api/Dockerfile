FROM python:3.14-slim
# uv 판을 고정한다. latest는 빌드할 때마다 다른 uv가 들어올 수 있다(설계서 8절).
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-cache
ENV PATH="/app/.venv/bin:$PATH"
COPY api/ api/
ARG MODEL_IMPL=rule
ENV MODEL_IMPL=${MODEL_IMPL}
EXPOSE 8080
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8080"]
