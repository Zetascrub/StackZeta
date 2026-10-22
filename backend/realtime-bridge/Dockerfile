FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libopus0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bridge.py privacy_gate.py forwarder.py .
RUN useradd --system --uid 10001 bridge
USER bridge
EXPOSE 8010
CMD ["python", "bridge.py"]
