# CAHON — server mode image.
# Data (notes, passwords, uploads, index) lives in /data: mount a persistent
# volume there, or it is lost when the container is replaced.
# Stage 1: the Rust text readers (native/), built as a Python wheel.
FROM ghcr.io/pyo3/maturin:latest AS native
COPY native /native
RUN maturin build --release --manifest-path /native/Cargo.toml --out /wheels

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Tesseract + Thai/English data: reads scanned PDFs and images (OCR).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-tha tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
# Fast Word/Excel/PowerPoint readers (falls back to Python if this is missing).
COPY --from=native /wheels /wheels
RUN pip install /wheels/*.whl && rm -rf /wheels

COPY cahon ./cahon

# Run as an unprivileged user that owns /data.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data && chown 10001:10001 /data
USER 10001

ENV CAHON_MODE=server \
    CAHON_DATA_DIR=/data \
    CAHON_PORT=8765
VOLUME ["/data"]
EXPOSE 8765

# CAHON_PASSWORD (login password) must be provided at runtime.
CMD ["python", "-m", "cahon"]
