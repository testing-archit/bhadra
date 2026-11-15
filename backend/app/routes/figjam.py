"""Pair a recorder's FigJam plugin with this call; no Figma account key stored."""
import datetime as dt
import hashlib
import re
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.cors import CORSMiddleware

from app.database.db import get_db
from app.database.models import CaptureRequest, FigJamConnection, FigJamDelivery, MeetingAgentJob, MeetingBoard, User
from app.dependencies import get_current_user
from app.rate_limit import limiter
from app.routes.boards import _readable_capture, BoardUpdate
from app.services import board_service, figjam_service

router = APIRouter(prefix='/api/figjam', tags=['figjam'])


class BridgeCors:
    def __init__(self, app):
        self.app = app
        self.bridge = CORSMiddleware(app, allow_origins=['null', 'https://www.figma.com'],
            allow_methods=['POST'], allow_headers=['Authorization', 'Content-Type'])

    async def __call__(self, scope, receive, send):
        target = self.bridge if scope.get('path', '').startswith('/api/figjam/bridge/') else self.app
        await target(scope, receive, send)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class PairRequest(BaseModel):
    file_url: str = Field(max_length=500)


class Redeem(BaseModel):
    code: str = Field(min_length=24, max_length=100)
    file_key: str = Field(min_length=1, max_length=100)


async def recorder(db, user, capture_id):
    capture = await _readable_capture(db, user, capture_id)
    if capture.user_id != user.id:
        raise HTTPException(403, 'Only the person who requested this recording can connect a board.')
    if capture.status != 'capturing':
        raise HTTPException(409, 'Connect FigJam while the notetaker is in the meeting.')
    return capture


@router.post('/captures/{capture_id}/pair')
@limiter.limit('10/minute')
async def pair(request: Request, response: Response, capture_id: uuid.UUID, body: PairRequest,
               user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    capture = await recorder(db, user, capture_id)
    match = re.fullmatch(r'https://(?:www\.)?figma\.com/(?:board|file)/([A-Za-z0-9]{6,100})(?:/[^?#]*)?(?:\?[^#]*)?(?:#.*)?', body.file_url.strip())
    if not match:
        raise HTTPException(422, 'Paste a FigJam board link from figma.com.')
    connection = await figjam_service.connection_for(db, capture.id)
    if connection and await db.scalar(select(MeetingAgentJob.id).where(
        MeetingAgentJob.capture_request_id == capture.id, MeetingAgentJob.state.in_(['accepted', 'running'])).limit(1)):
        raise HTTPException(409, 'Finish or cancel active commands before reconnecting FigJam.')
    if connection is None:
        connection = FigJamConnection(capture_request_id=capture.id, user_id=user.id)
        db.add(connection)
    code = secrets.token_urlsafe(24)
    connection.file_key = match[1]
    connection.file_url = 'https://www.figma.com/board/' + match[1]
    connection.pair_hash, connection.token_hash = digest(code), None
    connection.last_seen_at = None
    connection.pair_expires_at = figjam_service.now()+dt.timedelta(minutes=5)
    connection.expires_at = figjam_service.now()+dt.timedelta(hours=8)
    await db.flush()
    board = await board_service.ensure_for_capture(db, capture)
    board.paused = True
    # Saved revisions preserve the previous draft. The FigJam mirror starts
    # empty so connecting never exports earlier meeting content implicitly.
    await board_service.save_snapshot(db, board, expected_version=board.version, nodes=[], edges=[], actor_id=user.id, source='figjam_connected')
    await db.commit()
    response.headers['Cache-Control'] = 'no-store'
    return {'code': code, 'file_url': connection.file_url, 'expires_in_seconds': 300}


@router.get('/captures/{capture_id}')
async def status(capture_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _readable_capture(db, user, capture_id)
    connection = await figjam_service.connection_for(db, capture_id)
    return {'provider': 'figjam', 'configured': bool(connection), 'connected': bool(connection and figjam_service.connected(connection)),
            'file_url': connection.file_url if connection else None, 'can_connect': (await db.get(CaptureRequest, capture_id)).user_id == user.id}


@router.delete('/captures/{capture_id}')
async def disconnect(capture_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await recorder(db, user, capture_id)
    connection = await figjam_service.connection_for(db, capture_id)
    if connection:
        # Retain the selected destination: losing a plugin connection must not
        # silently redirect subsequent writes to a different board.
        connection.token_hash = connection.pair_hash = None
    await db.commit()
    return {'disconnected': True}


@router.post('/bridge/pair')
@limiter.limit('10/minute')
async def redeem(request: Request, response: Response, body: Redeem, db: AsyncSession = Depends(get_db)):
    connection = await db.scalar(select(FigJamConnection).where(FigJamConnection.pair_hash == digest(body.code)).with_for_update())
    if connection is None or connection.pair_expires_at <= figjam_service.now() or connection.file_key != body.file_key:
        raise HTTPException(401, 'This pairing code is invalid, expired, or belongs to another file.')
    capture = await db.get(CaptureRequest, connection.capture_request_id)
    if capture.status != 'capturing':
        raise HTTPException(409, 'This meeting is no longer recording.')
    token = secrets.token_urlsafe(32)
    connection.pair_hash = None
    connection.token_hash, connection.last_seen_at = digest(token), figjam_service.now()
    await db.commit()
    response.headers['Cache-Control'] = 'no-store'
    return {'token': token, 'connection_id': str(connection.id), 'file_url': connection.file_url}


async def bridge(request, db):
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if scheme != 'Bridge' or len(token) > 100 or len(token) < 32:
        raise HTTPException(401, 'Pair the FigJam plugin first.')
    connection = await db.scalar(select(FigJamConnection).where(FigJamConnection.token_hash == digest(token)).with_for_update())
    if connection is None or connection.expires_at <= figjam_service.now():
        raise HTTPException(401, 'Reconnect FigJam to continue.')
    capture = await db.get(CaptureRequest, connection.capture_request_id)
    if capture is None or capture.status != 'capturing':
        raise HTTPException(410, 'The meeting has ended.')
    connection.last_seen_at = figjam_service.now()
    return connection


@router.post('/bridge/poll')
@limiter.limit('600/minute')
async def poll(request: Request, db: AsyncSession = Depends(get_db)):
    connection = await bridge(request, db)
    rows = (await db.scalars(select(FigJamDelivery).where(FigJamDelivery.connection_id == connection.id,
        FigJamDelivery.state == 'pending').order_by(FigJamDelivery.expires_at).with_for_update())).all()
    result = None
    for row in rows:
        job = await db.get(MeetingAgentJob, row.job_id)
        if row.expires_at <= figjam_service.now() or job.state != 'running':
            row.state = 'expired'
        elif result is None:
            result = {'id': str(row.id), 'baseline': row.baseline, 'snapshot': row.snapshot,
                      'expires_at': row.expires_at.isoformat()}
    board = await db.scalar(select(MeetingBoard).where(MeetingBoard.capture_request_id == connection.capture_request_id))
    version = board.version
    await db.commit()
    return {'delivery': result, 'version': version}


class Acknowledgment(BaseModel):
    state: str = Field(pattern='^(applied|conflict|failed)$')


@router.post('/bridge/disconnect')
async def bridge_disconnect(request: Request, db: AsyncSession = Depends(get_db)):
    connection = await bridge(request, db)
    connection.token_hash = None
    await db.commit()
    return {'disconnected': True}


@router.post('/bridge/snapshot')
async def sync_snapshot(request: Request, body: BoardUpdate, db: AsyncSession = Depends(get_db)):
    connection = await bridge(request, db)
    if await db.scalar(select(MeetingAgentJob.id).where(MeetingAgentJob.capture_request_id == connection.capture_request_id,
        MeetingAgentJob.state.in_(['accepted', 'running'])).limit(1)):
        raise HTTPException(409, 'A command is running. Sync again after it finishes.')
    board = await db.scalar(select(MeetingBoard).where(MeetingBoard.capture_request_id == connection.capture_request_id).with_for_update())
    if board.version != body.expected_version:
        raise HTTPException(409, 'The board changed. Refresh before syncing.')
    nodes, edges = [node.model_dump() for node in body.nodes], [edge.model_dump() for edge in body.edges]
    if nodes != board.nodes or edges != board.edges:
        await board_service.save_snapshot(db, board, expected_version=board.version, nodes=nodes, edges=edges,
            actor_id=connection.user_id, source='figjam_manual')
    await db.commit()
    return {'version': board.version}


@router.post('/bridge/deliveries/{delivery_id}/ack')
async def acknowledge(request: Request, delivery_id: uuid.UUID, body: Acknowledgment, db: AsyncSession = Depends(get_db)):
    connection = await bridge(request, db)
    row = await db.scalar(select(FigJamDelivery).where(FigJamDelivery.id == delivery_id,
        FigJamDelivery.connection_id == connection.id).with_for_update())
    if row is None:
        raise HTTPException(404, 'Delivery not found.')
    if row.state == 'pending':
        row.state = body.state
    await db.commit()
    return {'state': row.state}
