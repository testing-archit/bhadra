import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.routes import figjam, gnani_lab, khata
from app.rate_limit import limiter
from app.routes import admin, auth, boards, bot, calendar, capture, chat, decisions, digest, email, jira, meeting_workspace, meetings, notifications, policy_chat, projects, recordings, recycle_bin, tasks, transcribe, tts, live, recap, vocabulary, voice
from app import mcp_server
from app.services import calendar_service, email_service, jira_service, processing_service, usage_ledger, meeting_agent

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        interrupted = await processing_service.fail_interrupted_stages()
        if interrupted:
            logger.warning("Marked %d interrupted processing stage(s) as failed", interrupted)
    except Exception:
        # A database hiccup at boot must not stop the API from serving.
        logger.exception("Could not check for interrupted processing stages")
    # AI calls run in worker threads; their cost records are written here.
    usage_ledger.bind_loop(asyncio.get_running_loop())
    # Follows linked Google Calendars and queues the notetaker for meetings.
    calendar_task = asyncio.create_task(calendar_service.run_forever())
    # Sends queued emails (and schedules the morning/Monday ones).
    email_task = asyncio.create_task(email_service.run_forever())
    # Copies status changes made in Jira back onto linked tasks.
    jira_task = asyncio.create_task(jira_service.run_forever())
    agent_task = asyncio.create_task(meeting_agent.run_forever())
    # The MCP connector's session manager lives as long as the app.
    tasks = (calendar_task, email_task, jira_task, agent_task)
    try:
        async with mcp_server.server.session_manager.run():
            yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Wilco", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(meeting_workspace.router)
app.include_router(meetings.router)
app.include_router(boards.router)
app.include_router(capture.router)
app.include_router(calendar.router)
app.include_router(tasks.router)
app.include_router(jira.router)
app.include_router(decisions.router)
app.include_router(projects.router)
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(transcribe.router)
app.include_router(digest.router)
app.include_router(policy_chat.router)
app.include_router(recordings.router)
app.include_router(recycle_bin.router)
app.include_router(notifications.router)
app.include_router(bot.router)
app.include_router(email.router)
app.include_router(vocabulary.router)
app.include_router(tts.router)
app.include_router(live.router)
app.include_router(recap.router)
app.include_router(voice.router)
app.include_router(figjam.router)
app.include_router(gnani_lab.router)
app.include_router(khata.router)
app.add_middleware(figjam.BridgeCors)
# Wilco as an MCP server for Claude and other assistants (connector token).
app.mount(mcp_server.MCP_PATH, mcp_server.http_app())


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
