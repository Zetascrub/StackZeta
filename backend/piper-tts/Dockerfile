FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "piper-tts[http]"

# Voice model files (.onnx + .onnx.json) live in a mounted volume at /data
# so they persist across rebuilds and aren't baked into the image.
WORKDIR /data

EXPOSE 5000

# en_US-lessac-medium is a reasonable default English voice; override VOICE
# at `docker compose run` / via environment if a different one is preferred.
ENV VOICE=en_US-lessac-medium

CMD ["sh", "-c", "python3 -m piper.download_voices $VOICE --data-dir /data || true && python3 -m piper.http_server -m $VOICE --data-dir /data --host 0.0.0.0 --port 5000"]
