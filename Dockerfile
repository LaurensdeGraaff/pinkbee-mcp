FROM python:3.12-slim AS build

WORKDIR /build
RUN pip install --no-cache-dir hatchling
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip wheel --no-cache-dir --no-deps -w /wheels .

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PINKBEE_MCP_TRANSPORT=streamable-http \
    PINKBEE_MCP_HOST=0.0.0.0 \
    PINKBEE_MCP_PORT=8080

COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

RUN useradd --create-home --uid 10001 pinkbee
USER pinkbee

EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-m", "pinkbee_mcp.healthcheck"]

ENTRYPOINT ["python", "-m", "pinkbee_mcp"]
