import asyncio
import datetime
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.config import settings
from app.database.db import async_session
from app.database.models import Decision, Meeting, MeetingTask, Risk, Trace, User
from app.dependencies import create_access_token
from app.main import app

# Every row created by this suite is tagged with this prefix so cleanup can
# find it reliably, regardless of which test created it or whether it failed
# partway through.
TEST_PREFIX = "pytest_"


def auth_headers(user: User) -> dict:
    token = create_access_token(user.id, user.email)
    return {"Authorization": f"Bearer {token}"}


# --- Database availability ---------------------------------------------------
# The test database is a real, network-reachable Postgres instance, and it is
# routinely unreachable from a developer machine that is not IP-allowlisted.
# Without this guard every database-backed test spends its full 60-second
# connect timeout before erroring, turning a 30-second suite into a 75-minute
# one and burying the tests that *did* run under a wall of timeouts.
#
# It also keeps the credential out of the logs: asyncpg's connection traceback
# prints the full DSN — password included — for every failure, which is fine on
# a laptop and a credential leak in CI.

DB_PROBE_TIMEOUT_SECONDS = 5.0
_db_state: dict = {}


async def _probe_database() -> str | None:
    """Returns None when the database is usable, or a short reason when it is
    not. Deliberately never includes connection credentials in that reason."""
    try:
        async with asyncio.timeout(DB_PROBE_TIMEOUT_SECONDS):
            async with async_session() as db:
                await db.execute(text("SELECT 1"))
        return None
    except TimeoutError:
        return f"no response within {DB_PROBE_TIMEOUT_SECONDS:.0f}s"
    except Exception as error:
        # Type only — the message can carry the DSN.
        return type(error).__name__


@pytest_asyncio.fixture(scope="session", autouse=True)
async def database_available():
    reason = await _probe_database()
    _db_state["reason"] = reason
    if reason is not None:
        print(
            f"\n[conftest] Test database unreachable ({reason}) — "
            "database-backed tests will be skipped. Check your IP allowlist "
            "and DATABASE_URL.\n"
        )
    return reason is None


def require_database() -> None:
    """Call from any fixture that needs the database."""
    reason = _db_state.get("reason", "not probed")
    if reason is not None:
        pytest.skip(f"test database unreachable ({reason})")


@pytest_asyncio.fixture(scope="session")
async def client():
    # ASGITransport calls the app in-process on the current event loop — no
    # separate thread/loop like Starlette's sync TestClient uses, which is
    # what caused asyncpg's "another operation is in progress" when mixed
    # with the module-level engine used by fixtures below.
    #
    # raise_app_exceptions=False makes unhandled exceptions come back as a
    # real 500 response (like a deployed server), instead of re-raising the
    # Python exception into the test process.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def member_user():
    """A regular, non-admin user scoped to the 'Engineering' department."""
    require_database()
    email = f"{TEST_PREFIX}member_{uuid.uuid4().hex[:8]}@example.com"
    assert email not in settings.admin_email_list

    async with async_session() as db:
        user = User(
            email=email, name=TEST_PREFIX + "user", google_sub=f"{TEST_PREFIX}{uuid.uuid4()}",
            department="Engineering",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    yield user

    async with async_session() as db:
        await db.execute(Trace.__table__.delete().where(Trace.user_id == user.id))
        obj = await db.get(User, user.id)
        if obj:
            await db.delete(obj)
            await db.commit()


@pytest_asyncio.fixture
async def other_member_user():
    """A second regular user in a different department ('Sales')."""
    require_database()
    email = f"{TEST_PREFIX}sales_{uuid.uuid4().hex[:8]}@example.com"

    async with async_session() as db:
        user = User(
            email=email, name=TEST_PREFIX + "user", google_sub=f"{TEST_PREFIX}{uuid.uuid4()}",
            department="Sales",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    yield user

    async with async_session() as db:
        await db.execute(Trace.__table__.delete().where(Trace.user_id == user.id))
        obj = await db.get(User, user.id)
        if obj:
            await db.delete(obj)
            await db.commit()


@pytest_asyncio.fixture
async def admin_user():
    """A user whose email is in ADMIN_EMAILS — sees every department."""
    require_database()
    assert settings.admin_email_list, (
        "ADMIN_EMAILS must be set in the test environment for admin tests to run"
    )
    email = settings.admin_email_list[0]

    async with async_session() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(email=email, name="admin", google_sub=f"{TEST_PREFIX}{uuid.uuid4()}")
            db.add(user)
            await db.commit()
            await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def make_meeting():
    """Directly inserts a Meeting bypassing the ingest pipeline, for tests
    that only need existing data to query against."""
    require_database()
    created_ids = []

    async def _make(user: User, title: str, department: str | None, transcript: str = "test transcript"):
        async with async_session() as db:
            meeting = Meeting(
                user_id=user.id,
                title=TEST_PREFIX + title,
                date=datetime.datetime.now(datetime.UTC),
                transcript=transcript,
                summary="test summary",
                duration_minutes=1,
                department=department,
            )
            db.add(meeting)
            await db.commit()
            await db.refresh(meeting)
        created_ids.append(meeting.id)
        return meeting

    yield _make

    async with async_session() as db:
        for mid in created_ids:
            await db.execute(Trace.__table__.delete().where(Trace.meeting_id == mid))
            await db.execute(MeetingTask.__table__.delete().where(MeetingTask.meeting_id == mid))
            await db.execute(Decision.__table__.delete().where(Decision.meeting_id == mid))
            await db.execute(Risk.__table__.delete().where(Risk.meeting_id == mid))
            await db.execute(Meeting.__table__.delete().where(Meeting.id == mid))
        await db.commit()


@pytest.fixture
def mock_extraction():
    """Patches ai_extractor so tests never call the real Gemini API."""
    with patch("app.services.ai_extractor.extract_from_transcript") as m:
        m.return_value = {
            "title": "",
            "tasks": [{"task": "Do the thing", "assignedTo": "Someone", "dueDate": "Friday", "priority": "Medium", "project": ""}],
            "decisions": [{"decision": "Use X", "reason": "It is good", "alternatives": [], "participants": [], "project": ""}],
            "risks": [],
            "summary": "A test summary.",
            "key_topics": [],
            "open_questions": [],
            "highlights": [],
            "next_steps": [],
            "speaker_activity": [],
            "input_tokens": 10,
            "cache_tokens_read": 0,
            "cache_tokens_written": 0,
            "output_tokens": 5,
        }
        yield m


@pytest.fixture
def mock_qdrant_upsert():
    with patch("app.services.qdrant_service.upsert_meeting") as m:
        yield m


@pytest.fixture(autouse=True)
def company_email_domain():
    """Test colleagues are @example.com: that is "the company" for meeting
    emails (INTERNAL_EMAIL_DOMAINS), as example.com is in production."""
    with patch.object(settings, "internal_email_domains", "example.com"):
        yield


@pytest.fixture(autouse=True)
def mock_contradiction_check():
    """Patches the contradiction check so tests never call Qdrant/Gemini for
    it. Autouse because ingest hits this on every decision — individual tests
    override the return value with a second `with patch(...)` when they want
    to assert on the conflict-note path."""
    with patch("app.services.contradiction_service.check_for_contradiction") as m:
        m.return_value = {"note": None, "usage": None}
        yield m


@pytest_asyncio.fixture(autouse=True, scope="session")
async def cleanup_all_test_data():
    yield
    if _db_state.get("reason") is not None:
        return  # nothing was written, and the sweep would only time out again
    # Final safety-net sweep in case any per-test cleanup fixture didn't run
    # (e.g. the test itself crashed before reaching its fixture teardown).
    async with async_session() as db:
        result = await db.execute(select(Meeting.id).where(Meeting.title.like(f"{TEST_PREFIX}%")))
        meeting_ids = [row[0] for row in result.all()]
        for mid in meeting_ids:
            await db.execute(Trace.__table__.delete().where(Trace.meeting_id == mid))
            await db.execute(MeetingTask.__table__.delete().where(MeetingTask.meeting_id == mid))
            await db.execute(Decision.__table__.delete().where(Decision.meeting_id == mid))
            await db.execute(Risk.__table__.delete().where(Risk.meeting_id == mid))
        await db.execute(Meeting.__table__.delete().where(Meeting.id.in_(meeting_ids)))

        result = await db.execute(select(Trace.id).where(Trace.meeting_title.like(f"{TEST_PREFIX}%")))
        trace_ids = [row[0] for row in result.all()]
        await db.execute(Trace.__table__.delete().where(Trace.id.in_(trace_ids)))

        result = await db.execute(select(User.id).where(User.google_sub.like(f"{TEST_PREFIX}%")))
        user_ids = [row[0] for row in result.all()]
        # Catches traces tied to a test user by user_id even when their
        # meeting_title doesn't carry the TEST_PREFIX (e.g. chat traces are
        # labelled "Chat — ..."), which would otherwise leave them orphaned
        # and block the user DELETE below with a FK violation.
        await db.execute(Trace.__table__.delete().where(Trace.user_id.in_(user_ids)))
        await db.execute(User.__table__.delete().where(User.id.in_(user_ids)))
        await db.commit()
