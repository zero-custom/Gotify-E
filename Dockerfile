FROM python:3.14-alpine AS builder

WORKDIR /build

RUN apk add --no-cache file-dev build-base
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.14-alpine

WORKDIR /app

COPY requirements.txt .
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --only-binary :all: --find-links /wheels -r requirements.txt && \
    rm -rf /wheels requirements.txt && \
    apk add --no-cache file

COPY app/ .
RUN chmod +x docker.sh

EXPOSE 8765

HEALTHCHECK --interval=10s --start-period=10s --timeout=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/version')" || exit 1

ENTRYPOINT ["/app/docker.sh"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8765", "--proxy-headers"]
