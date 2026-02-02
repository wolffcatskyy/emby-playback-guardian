FROM python:3.11-alpine

LABEL maintainer="github.com/wolffcatskyy"
LABEL description="Protects Emby/Jellyfin playback by pausing tasks and throttling downloads"
LABEL org.opencontainers.image.source="https://github.com/wolffcatskyy/emby-playback-guardian"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY guardian.py .

RUN adduser -D -u 1000 guardian
USER guardian

EXPOSE 8095

HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8095/health')" || exit 1

CMD ["python", "-u", "guardian.py"]
