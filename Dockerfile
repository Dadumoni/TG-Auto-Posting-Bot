FROM python:3.10-slim AS builder

WORKDIR /build

# Install build tools only in builder stage to compile any C-extensions cleanly
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Install only prebuilt wheels (no gcc/headers in final image -> lightweight footprint)
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* && rm -rf /wheels

COPY . .

EXPOSE 8080

CMD ["python", "main.py"]
