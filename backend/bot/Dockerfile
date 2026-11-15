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
COPY requirements-tracing.txt .
ARG ENABLE_COMMAND_TRACING=0
RUN if [ "$ENABLE_COMMAND_TRACING" = "1" ]; then pip install --no-cache-dir -r requirements-tracing.txt; fi

COPY entrypoint.sh command_runtime.py agent_client.py board_intent.py board_presenter.py board_presenter.js browser_voice.py config.py google_calendar.py meet_chat.py meeting_session.py scheduler.py teams_dom.py uploader.py ./
COPY assets/ assets/
RUN python -c "import agent_client, board_presenter, browser_voice, command_runtime, meeting_session"
RUN chmod +x entrypoint.sh

ENV STATE_DIR=/data \
    PYTHONUNBUFFERED=1
VOLUME /data

ENTRYPOINT ["./entrypoint.sh"]
