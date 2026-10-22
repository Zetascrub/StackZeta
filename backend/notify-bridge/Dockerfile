FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py panel_security.py device_controls.py ./
COPY control.html login.html ./

EXPOSE 8090

CMD ["python3", "app.py"]
