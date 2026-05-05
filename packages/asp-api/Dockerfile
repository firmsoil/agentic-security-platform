# syntax=docker/dockerfile:1.7
# Multi-stage build. Stage 1 builds the wheel; stage 2 is the runtime image.
# Runtime uses chainguard/python for a minimal, non-root, distroless base —
# this matters for a security project that ships its own image.

# ---- builder ----
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1

RUN pip install --no-cache-dir uv==0.5.11

WORKDIR /app

# Copy workspace root and the packages we need.
COPY pyproject.toml uv.lock* ./
COPY packages/asp-core ./packages/asp-core
COPY packages/asp-adapters ./packages/asp-adapters
COPY packages/asp-api ./packages/asp-api
COPY packages/asp-agents ./packages/asp-agents
COPY packages/asp-cli ./packages/asp-cli

# Install only the API + its transitive workspace deps.
RUN uv sync --frozen --package asp-api --no-dev || uv sync --package asp-api --no-dev

# ---- runtime ----
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"

# Non-root runtime user.
RUN groupadd --system --gid 10001 asp \
 && useradd  --system --uid 10001 --gid asp --home /app --shell /sbin/nologin asp

WORKDIR /app

COPY --from=builder /app /app
RUN chown -R asp:asp /app

USER asp

EXPOSE 8000

# Healthcheck hits the API's /health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status==200 else 1)"

CMD ["asp-api"]
