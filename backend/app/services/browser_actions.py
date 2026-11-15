"""Capture-scoped browser outbox. Dispatch once; ambiguous external writes stay ambiguous."""
import asyncio
import datetime as dt
import re
import uuid

from sqlalchemy import select

from app.database.db import async_session
from app.database.models import CaptureRequest, FigJamConnection, MeetingAgentJob, MeetingBrowserAction


def board_url(value):
    match = re.fullmatch(r'https://(?:www\.)?figma\.com/board/([A-Za-z0-9]{6,100})(?:/[^?#]*)?(?:\?[^#]*)?(?:#.*)?', value or '')
    return ('https://www.figma.com/board/' + match[1], match[1]) if match else None


async def active(db, capture_id, job_id):
    job = await db.scalar(select(MeetingAgentJob).where(MeetingAgentJob.id == job_id,
        MeetingAgentJob.capture_request_id == capture_id).with_for_update())
    capture = await db.get(CaptureRequest, capture_id)
    now = dt.datetime.now(dt.UTC)
    if (not job or job.state != 'running' or job.deadline_at <= now or not job.lease_until
            or job.lease_until <= now or not capture or capture.status != 'capturing'):
        raise LookupError('This browser request is no longer active.')
    return job


async def claim(db, capture_id):
    rows = (await db.scalars(select(MeetingBrowserAction).where(
        MeetingBrowserAction.capture_request_id == capture_id, MeetingBrowserAction.state == 'pending')
        .order_by(MeetingBrowserAction.created_at).limit(8))).all()
    for candidate in rows:
        try:
            job = await active(db, capture_id, candidate.job_id)
        except LookupError:
            candidate.state = 'expired'
            continue
        row = await db.scalar(select(MeetingBrowserAction).where(MeetingBrowserAction.id == candidate.id)
            .with_for_update().execution_options(populate_existing=True))
        if row.state != 'pending':
            continue
        if row.expires_at <= dt.datetime.now(dt.UTC):
            row.state = 'expired'
            continue
        row.state, row.claim_token = 'claimed', uuid.uuid4()
        result = {'id': str(row.id), 'command_id': str(job.command_id),
                  'claim_token': str(row.claim_token), 'operation': row.operation,
                  'payload': row.payload, 'expires_at': row.expires_at.isoformat()}
        await db.commit()
        return result
    await db.commit()
    return None


async def validate(db, capture_id, identifier, token):
    candidate = await db.get(MeetingBrowserAction, identifier)
    if not candidate or candidate.capture_request_id != capture_id or candidate.claim_token != token:
        raise LookupError('Browser request not found.')
    await active(db, capture_id, candidate.job_id)
    row = await db.scalar(select(MeetingBrowserAction).where(MeetingBrowserAction.id == identifier)
        .with_for_update().execution_options(populate_existing=True))
    if row.state != 'claimed' or row.expires_at <= dt.datetime.now(dt.UTC):
        raise LookupError('This browser request is no longer active.')
    return row


async def complete(db, capture_id, identifier, token, result):
    row = await validate(db, capture_id, identifier, token)
    url = board_url(result.get('file_url'))
    if result['outcome'] == 'applied' and not url:
        raise ValueError('A native FigJam URL is required for success.')
    if url:
        capture = await db.get(CaptureRequest, capture_id)
        connection = await db.scalar(select(FigJamConnection).where(FigJamConnection.capture_request_id == capture_id))
        if connection and connection.file_key != url[1]:
            raise ValueError('The browser returned a different FigJam file.')
        if not connection:
            connection = FigJamConnection(capture_request_id=capture_id, user_id=capture.user_id,
                file_url=url[0], file_key=url[1], transport='browser',
                pair_expires_at=dt.datetime.now(dt.UTC), expires_at=dt.datetime.now(dt.UTC)+dt.timedelta(hours=8))
            db.add(connection)
            from app.services import board_service
            board = await board_service.ensure_for_capture(db, capture)
            board.paused = True
            # Start the destination mirror empty; automatic notes were never
            # written to this native file. Earlier revisions remain preserved.
            if board.nodes or board.edges:
                await board_service.save_snapshot(db, board, expected_version=board.version,
                    nodes=[], edges=[], actor_id=capture.user_id, source='figjam_browser_connected')
        connection.last_seen_at = dt.datetime.now(dt.UTC)
    row.state, row.result = 'completed', {**result, 'file_url': url[0] if url else None}
    await db.commit()


async def enqueue(db, capture, job, index, operation, payload):
    command_id = uuid.uuid5(job.id, str(index))
    row = await db.scalar(select(MeetingBrowserAction).where(
        MeetingBrowserAction.capture_request_id == capture.id, MeetingBrowserAction.command_id == command_id))
    if row is None:
        row = MeetingBrowserAction(capture_request_id=capture.id, job_id=job.id, command_id=command_id,
            operation=operation, payload=payload, expires_at=job.deadline_at)
        db.add(row)
        await db.flush()
    return row


async def dispatch(db, capture, job, index, operation, payload, guard):
    await guard(db, job.id, job.lease_token)
    row = await enqueue(db, capture, job, index, operation, payload)
    identifier = row.id
    await db.commit()
    while dt.datetime.now(dt.UTC) < job.deadline_at:
        async with async_session() as state_db:
            await guard(state_db, job.id, job.lease_token)
            saved = await state_db.get(MeetingBrowserAction, identifier)
            if saved.state == 'completed':
                return saved.result
        await asyncio.sleep(.2)
    raise TimeoutError('Browser action expired')


def receipt(result, *, drawing=False):
    code = result.get('outcome')
    url = result.get('file_url')
    if code == 'applied' and board_url(url):
        return {'message': ('Updated FigJam: ' if drawing else 'Opened FigJam: ') + url}
    messages = {
        'auth_required': 'Wilco needs its one-time Figma browser sign-in before it can open boards. No meeting portal connection is needed.',
        'editor_unavailable': 'FigJam opened, but I could not confirm an editable board. Check the account permissions or onboarding screen.',
        'unsupported_edit': 'I could not safely apply this edit in FigJam. The browser currently supports adding small flows; existing objects were kept.',
        'uncertain': 'The FigJam action was interrupted or could not be verified. Check the board before retrying; I will not repeat uncertain writes.',
    }
    message = messages.get(code, messages['uncertain'])
    return {'message': message + (f' {url}' if board_url(url) else ''), 'needs_input': True}
