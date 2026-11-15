"""Read metadata only. Optional synthetic speech probe never reads meeting audio."""
import asyncio
import json
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import func, select
from app.config import settings
from app.database.db import async_session
from app.database.models import AiUsageEvent, MeetingAgentJob, MeetingBoard
from app.services import tts_service, usage_ledger


async def main():
    print(json.dumps({'speech_config': {
        'provider': 'gnani', 'configured': bool(settings.gnani_api_key),
        'host': urlparse(settings.gnani_tts_url).hostname,
        'model': settings.gnani_tts_model, 'voice': settings.gnani_tts_voice,
        'language': settings.gnani_tts_language, 'interactive_model': settings.gemini_fast_model,
    }}))
    async with async_session() as db:
        jobs = (await db.scalars(select(MeetingAgentJob).order_by(MeetingAgentJob.created_at.desc()).limit(15))).all()
        for job in jobs:
            nodes = await db.scalar(select(MeetingBoard.nodes).where(MeetingBoard.capture_request_id == job.capture_request_id))
            print(json.dumps({'recent_job': {
                'id': str(job.id), 'state': job.state, 'phase': job.phase,
                'tool': job.payload.get('tool'), 'plan_tools': [p.get('tool') for p in job.plan or []],
                'receipts': len(job.receipts or []), 'board_nodes': len(nodes or []),
                'completion_ms': round((job.finished_at-job.created_at).total_seconds()*1000) if job.finished_at else None,
            }}))
        usage = (await db.execute(select(AiUsageEvent.feature, AiUsageEvent.model, func.count()).where(
            AiUsageEvent.feature.in_(['speech', 'live_conversation', 'meeting_agent_plan', 'board_command'])
        ).group_by(AiUsageEvent.feature, AiUsageEvent.model))).all()
        print(json.dumps({'paid_usage_counts': [list(row) for row in usage]}))
    started = time.monotonic()
    try:
        audio = await tts_service.synthesize('Namaste. I am ready to help your team.')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'probe.mp3'
            path.write_bytes(audio)
            proc = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_name,sample_rate,channels:format=duration', '-of', 'json', str(path)], capture_output=True, text=True, timeout=10)
            metadata = json.loads(proc.stdout) if proc.returncode == 0 else {'decode': 'failed'}
        print(json.dumps({'synthetic_speech': {'elapsed_ms': round((time.monotonic()-started)*1000), 'bytes': len(audio), **metadata}}))
    except Exception as error:
        print(json.dumps({'synthetic_speech': {'error_type': type(error).__name__}}))
    pending = list(usage_ledger._pending)
    if pending:
        await asyncio.gather(*pending)


asyncio.run(main())
