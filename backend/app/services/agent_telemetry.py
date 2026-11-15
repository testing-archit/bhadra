"""Best-effort, content-free command timings with optional MLflow export."""
import json
import logging
import os
import time
from contextlib import contextmanager

log = logging.getLogger(__name__)


@contextmanager
def stage(job_id, phase, **metrics):
    start = time.monotonic()
    outcome = 'ok'
    exporter = None
    span = None
    if os.environ.get('MEETING_AGENT_MLFLOW') == '1':
        try:
            import mlflow
            exporter = mlflow.start_span(name='meeting.agent.' + phase,
                attributes={'job_id': str(job_id), **metrics})
            span = exporter.__enter__()
        except Exception:
            exporter = None
            log.warning('Agent trace exporter unavailable')
    try:
        yield
    except BaseException:
        outcome = 'interrupted'
        raise
    finally:
        log.info('agent_timing %s', json.dumps({'job_id': str(job_id), 'phase': phase,
            'outcome': outcome, 'duration_ms': round((time.monotonic()-start)*1000, 2), **metrics}))
        if exporter:
            try:
                try:
                    span.set_attribute('outcome', outcome)
                finally:
                    exporter.__exit__(None, None, None)  # Never export provider exception bodies.
            except Exception:
                log.warning('Agent trace exporter unavailable')
