# Career Context Hub - hosted mode (HTTP + token auth). Put a TLS reverse proxy (Caddy/Nginx) in front.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    CAREER_HUB_MODE=hosted CAREER_HUB_HOST=0.0.0.0 CAREER_HUB_PORT=8000 \
    CAREER_HUB_DB=/data/career.db

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install . && useradd --create-home --uid 10001 hub && mkdir /data && chown hub /data
USER hub
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
CMD ["career-hub"]
