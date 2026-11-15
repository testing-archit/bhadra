FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-agent-tracing.txt ./
RUN pip install --no-cache-dir -r requirements.txt
ARG ENABLE_AGENT_TRACING=0
RUN if [ "$ENABLE_AGENT_TRACING" = "1" ]; then pip install --no-cache-dir -r requirements-agent-tracing.txt; fi

COPY . .
RUN python scripts/download_speaker_model.py

EXPOSE 8080
CMD ["sh", "-c", "python scripts/init_db.py && python scripts/backfill_meeting_projects.py && exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --proxy-headers --forwarded-allow-ips='*'"]
