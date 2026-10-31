# Search Anything — server mode image.
# Data (notes, passwords, uploads, index) lives in /data: mount a persistent
# volume there, or it is lost when the container is replaced.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY search_anything ./search_anything

# Run as an unprivileged user that owns /data.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data && chown 10001:10001 /data
USER 10001

ENV SA_MODE=server \
    SA_DATA_DIR=/data \
    SA_PORT=8765
VOLUME ["/data"]
EXPOSE 8765

# SA_PASSWORD (login password) must be provided at runtime.
CMD ["python", "-m", "search_anything"]
