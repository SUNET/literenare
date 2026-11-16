FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    GRANIAN_HOST=0.0.0.0 GRANIAN_PORT=8080 GRANIAN_WORKERS=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config.yaml ./
COPY data ./data

RUN useradd -r -u 10001 app && chown -R app /srv
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"
CMD ["granian", "--interface", "asgi", "--factory", "app.main:create_app"]
