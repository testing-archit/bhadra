"""Scoped FigJam bridge. Success requires the native plugin's acknowledgment."""
import asyncio
import datetime as dt
import uuid

from sqlalchemy import select
from app.database.db import async_session
from app.database.models import FigJamConnection, FigJamDelivery, MeetingBoardRevision
from app.services import board_service


def now():
    return dt.datetime.now(dt.UTC)


def connected(connection):
    if connection.transport == 'browser':
        return bool(connection.last_seen_at and connection.expires_at > now())
    return bool(connection.token_hash and connection.expires_at > now() and connection.last_seen_at
                and (now()-connection.last_seen_at).total_seconds() < 8)


async def connection_for(db, capture_id):
    return await db.scalar(select(FigJamConnection).where(FigJamConnection.capture_request_id == capture_id))


async def edit(db, capture, job, index, instruction, provider, guard, receipt):
    connection = await connection_for(db, capture.id)
    if connection is None:
        return False
    if not connected(connection):
        await receipt(db, {'message': 'Open the Wilco plugin in your connected FigJam file, then ask again.', 'needs_input': True})
        return True
    command_id = uuid.uuid5(job.id, str(index))
    delivery = await db.scalar(select(FigJamDelivery).where(
        FigJamDelivery.connection_id == connection.id, FigJamDelivery.command_id == command_id))
    if delivery is None:
        async def queue(db, result):
            await guard(db, job.id, job.lease_token)
            board = result['board']
            prior = await db.scalar(select(MeetingBoardRevision).where(
                MeetingBoardRevision.board_id == uuid.UUID(board['id']), MeetingBoardRevision.version == board['version']-1))
            baseline = {'nodes': prior.nodes, 'edges': prior.edges} if prior else {'nodes': [], 'edges': []}
            db.add(FigJamDelivery(connection_id=connection.id, command_id=command_id, job_id=job.id,
                baseline=baseline, snapshot=board, expires_at=job.deadline_at))
        result = await board_service.command_capture_board(db, capture.id, command_id, instruction,
            checkpoint=queue, run_provider=provider, context=job.payload.get('captions') or [])
        if result.get('needs_input'):
            await receipt(db, result)
            return True
        delivery = await db.scalar(select(FigJamDelivery).where(
            FigJamDelivery.connection_id == connection.id, FigJamDelivery.command_id == command_id))
        if delivery is None:
            # Never announce a native write from a local mirror alone.
            await receipt(db, {'message': 'I could not confirm a FigJam write. Please reconnect the plugin.', 'needs_input': True})
            return True
    delivery_id, url = delivery.id, connection.file_url
    await db.commit()
    # Provider work is already done; do not block a database transaction here.
    for _ in range(40):
        async with async_session() as state_db:
            await guard(state_db, job.id, job.lease_token)
            state = await state_db.get(FigJamDelivery, delivery_id)
            outcome = state.state if state else 'cancelled'
        if outcome != 'pending':
            break
        await asyncio.sleep(.2)
    if outcome == 'applied':
        result = {'message': f'Updated your shared FigJam board: {url}'}
    else:
        result = {'message': 'The FigJam edit was not confirmed. Open the plugin and check the board before retrying.', 'needs_input': True}
    # A timeout is ambiguous, not a successful write. Expire the outbox so a
    # plugin reconnect does not silently apply a request already reported stale.
    if outcome == 'pending':
        row = await db.scalar(select(FigJamDelivery).where(FigJamDelivery.id == delivery_id).with_for_update())
        if row.state == 'applied':
            result = {'message': f'Updated your shared FigJam board: {url}'}
        elif row.state == 'pending':
            row.state = 'expired'
    await receipt(db, result)
    return True
