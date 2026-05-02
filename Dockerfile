FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"

COPY drawflow_mcp ./drawflow_mcp
COPY skills ./skills

ENV DRAWFLOW_ARTIFACT_DIR=/data/artifacts

CMD ["python", "-m", "drawflow_mcp.server", "--transport", "http", "--host", "0.0.0.0", "--port", "8765"]
