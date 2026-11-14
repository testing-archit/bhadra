FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

RUN apt-get update && apt-get install -y --no-install-recommends \
    pulseaudio \
    pulseaudio-utils \
    xvfb \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY entrypoint.sh config.py google_calendar.py meeting_session.py scheduler.py teams_dom.py uploader.py ./
COPY assets/logo_card.png assets/
RUN chmod +x entrypoint.sh

ENV STATE_DIR=/data \
    PYTHONUNBUFFERED=1
VOLUME /data

ENTRYPOINT ["./entrypoint.sh"]
