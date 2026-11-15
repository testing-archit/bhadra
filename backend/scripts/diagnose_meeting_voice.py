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
from app.services import gemini_service
from app.services.board_commands import BoardCommandPlan, SYSTEM_PROMPT
from google.genai.errors import APIError


async def main():
    # Candidate compatibility probe for servers still on the preceding wrapper.
    # This changes only this diagnostic process, never the running application.
    if not hasattr(gemini_service, '_thinking_config'):
        from types import SimpleNamespace
        original_config = gemini_service.types.GenerateContentConfig
        original_thinking = gemini_service.types.ThinkingConfig
        def compatible_config(**kwargs):
            thinking = kwargs.get('thinking_config')
            if thinking is not None and thinking.thinking_budget is not None:
                kwargs['thinking_config'] = original_thinking(thinking_level='MINIMAL')
            kwargs.pop('temperature', None)
            return original_config(**kwargs)
        gemini_service.types = SimpleNamespace(GenerateContentConfig=compatible_config, ThinkingConfig=original_thinking)
        print(json.dumps({'candidate_compatibility_probe':True}))
    print(json.dumps({'speech_config': {
        'provider': 'gnani', 'configured': bool(settings.gnani_api_key),
        'host': urlparse(settings.gnani_tts_url).hostname,
        'model': settings.gnani_tts_model, 'voice': settings.gnani_tts_voice,
        'language': settings.gnani_tts_language, 'interactive_model': settings.gemini_fast_model,
        'agent_provider_seconds': settings.meeting_agent_provider_seconds,
    }}))
    try:
        plan, _ = gemini_service.generate_structured(SYSTEM_PROMPT,
            'Add one idea named Release check. Board: {"nodes":[],"edges":[]}', BoardCommandPlan,
            model=settings.gemini_fast_model, feature='agent_release_fast_probe', thinking_budget=0,
            timeout_seconds=settings.meeting_agent_provider_seconds, attempts=1)
        print(json.dumps({'fast_model_probe': 'ok', 'operations':len(plan.operations)}))
    except APIError as error:
        print(json.dumps({'fast_model_probe': 'provider_error', 'code':error.code,
            'message':str(error.message).replace(settings.gemini_api_key, '[REDACTED]')[:1500]}))
    except Exception as error:
        print(json.dumps({'fast_model_probe': 'failed', 'error_type':type(error).__name__}))
    for budget in (None, 0):
        try:
            reply, _ = gemini_service.generate_text('Reply with Ready.', 'Say Ready.', max_output_tokens=128,
                model=settings.gemini_fast_model, thinking_budget=budget, temperature=None,
                timeout_seconds=15, feature='voice_release_model_compatibility')
            print(json.dumps({'fast_text_probe': 'ok', 'thinking_budget':budget, 'reply_present':bool(reply)}))
        except APIError as error:
            print(json.dumps({'fast_text_probe':'provider_error', 'thinking_budget':budget,'code':error.code,
                'message':str(error.message).replace(settings.gemini_api_key,'[REDACTED]')[:1000]}))
    try:
        provider = gemini_service._client(15)
        names = [entry.name for entry in provider.models.list() if 'flash' in entry.name and ('lite' in entry.name or '3.' in entry.name)][:20]
        provider.close()
        print(json.dumps({'available_flash_models':names}))
    except Exception as error:
        print(json.dumps({'model_catalog_error':type(error).__name__}))
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
