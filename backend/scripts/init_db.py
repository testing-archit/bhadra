import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import models  # noqa: F401 — registers models on Base.metadata
from app.database.db import Base, engine


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all intentionally does not alter existing tables. Keep these
        # lightweight, idempotent additions here until formal migrations are
        # introduced so existing local installs gain centralized integrations.
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sheets_spreadsheet_id VARCHAR"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sheets_tasks_tab VARCHAR NOT NULL DEFAULT 'Tasks'"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sheets_notes_tab VARCHAR NOT NULL DEFAULT 'Meeting Notes'"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR NOT NULL DEFAULT 'member'"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'active'"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS job_title VARCHAR"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES teams(id) ON DELETE SET NULL"))
        for table in ("meetings", "projects", "tasks", "decisions", "risks"):
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"))
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES users(id) ON DELETE SET NULL"))
        await conn.execute(text("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS summary_verified_at TIMESTAMPTZ"))
        await conn.execute(text("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS summary_verified_by UUID REFERENCES users(id) ON DELETE SET NULL"))
        for table in ("tasks", "decisions", "risks"):
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ"))
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS verified_by UUID REFERENCES users(id) ON DELETE SET NULL"))
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_date DATE"))
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS parent_task_id UUID REFERENCES tasks(id) ON DELETE CASCADE"))
        await conn.execute(text("ALTER TABLE recording_sessions ADD COLUMN IF NOT EXISTS attendees JSONB"))
        # Makes a retried ingest idempotent — see Meeting.client_meeting_id.
        await conn.execute(text("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS client_meeting_id VARCHAR"))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_meeting_client_id "
            "ON meetings(user_id, client_meeting_id) WHERE client_meeting_id IS NOT NULL"
        ))
        # External share link — NULL until an attendee copies it.
        await conn.execute(text("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS share_token VARCHAR"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_meetings_share_token ON meetings(share_token)"))
        # Meeting access is attendee-based. Every pre-existing meeting keeps
        # working without a backfill because its recorder (meetings.user_id) is
        # always allowed in; this only adds the extra people.
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_meeting_attendees_user ON meeting_attendees(user_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_meeting_attendees_meeting ON meeting_attendees(meeting_id)"))
        # Meeting Assistant: transcript workspace, grounded insights, capture.
        # The new tables themselves come from create_all above.
        await conn.execute(text("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS source VARCHAR"))
        await conn.execute(text("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS template VARCHAR NOT NULL DEFAULT 'general'"))
        await conn.execute(text("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS transcript_revision INTEGER NOT NULL DEFAULT 1"))
        await conn.execute(text("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS insights_revision INTEGER"))
        for table in ("tasks", "decisions", "risks"):
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS evidence JSONB"))
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS ai_flags JSONB"))
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS origin VARCHAR NOT NULL DEFAULT 'ai'"))
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES users(id) ON DELETE SET NULL"))
        for column in ("overview TEXT", "sections JSONB", "template_sections JSONB", "follow_up_draft TEXT"):
            await conn.execute(text(f"ALTER TABLE meeting_insights ADD COLUMN IF NOT EXISTS {column}"))
        await conn.execute(text("ALTER TABLE memory_conversations ADD COLUMN IF NOT EXISTS scope_meeting_ids JSONB"))
        # Organisation-wide notetaker: one recording per meeting shared by
        # every colleague who asked for it, linked Google Calendars, and
        # invite-based access. New tables come from create_all above.
        await conn.execute(text("ALTER TABLE meeting_attendees ADD COLUMN IF NOT EXISTS access VARCHAR NOT NULL DEFAULT 'granted'"))
        await conn.execute(text("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS organizer_user_id UUID REFERENCES users(id) ON DELETE SET NULL"))
        await conn.execute(text("ALTER TABLE capture_requests ADD COLUMN IF NOT EXISTS source VARCHAR NOT NULL DEFAULT 'link'"))
        await conn.execute(text("ALTER TABLE capture_requests ADD COLUMN IF NOT EXISTS invitees JSONB"))
        await conn.execute(text("ALTER TABLE capture_requests ADD COLUMN IF NOT EXISTS organizer_email VARCHAR"))
        await conn.execute(text("ALTER TABLE capture_requests ADD COLUMN IF NOT EXISTS scheduled_start TIMESTAMPTZ"))
        await conn.execute(text("ALTER TABLE capture_requests ADD COLUMN IF NOT EXISTS scheduled_end TIMESTAMPTZ"))
        # Every existing request's requester becomes its first subscriber.
        await conn.execute(text(
            "INSERT INTO capture_subscribers (capture_request_id, user_id, source) "
            "SELECT id, user_id, 'link' FROM capture_requests "
            "ON CONFLICT ON CONSTRAINT uq_capture_subscriber DO NOTHING"
        ))
        # Recurring meeting series.
        await conn.execute(text("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS meeting_code VARCHAR"))
        await conn.execute(text("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS series_key VARCHAR"))
        await conn.execute(text("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS series_review JSONB"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_meetings_series_key ON meetings(series_key)"))
        await conn.execute(text("ALTER TABLE capture_requests ADD COLUMN IF NOT EXISTS series_key VARCHAR"))
        await conn.execute(text("ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS recurring_event_id VARCHAR"))
        # Automatic pre-meeting briefs.
        await conn.execute(text("ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS brief JSONB"))
        await conn.execute(text("ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS brief_generated_at TIMESTAMPTZ"))
        # Email: outbox + reset tokens come from create_all; user columns here.
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_prefs JSONB"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS sessions_valid_after TIMESTAMPTZ"))
        # Calendar push channels.
        for column in ("watch_channel_id VARCHAR UNIQUE", "watch_resource_id VARCHAR", "watch_token VARCHAR",
                       "watch_expires_at TIMESTAMPTZ", "watch_error TEXT"):
            await conn.execute(text(f"ALTER TABLE calendar_connections ADD COLUMN IF NOT EXISTS {column}"))
        # Jira: jira_connection comes from create_all; task link columns here.
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS jira_issue_key VARCHAR"))
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS jira_status VARCHAR"))
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS jira_synced_at TIMESTAMPTZ"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_jira_issue_key ON tasks(jira_issue_key)"))
        await conn.execute(text("ALTER TABLE task_history ADD COLUMN IF NOT EXISTS source VARCHAR"))
        # Connect with Jira (OAuth) next to the API-token connection.
        await conn.execute(text("ALTER TABLE jira_connection ADD COLUMN IF NOT EXISTS auth_type VARCHAR NOT NULL DEFAULT 'token'"))
        for column in ("cloud_id VARCHAR", "refresh_token_encrypted TEXT", "access_token_encrypted TEXT",
                       "access_token_expires_at TIMESTAMPTZ"):
            await conn.execute(text(f"ALTER TABLE jira_connection ADD COLUMN IF NOT EXISTS {column}"))
        for column in ("email", "api_token_encrypted", "default_project_key"):
            await conn.execute(text(f"ALTER TABLE jira_connection ALTER COLUMN {column} DROP NOT NULL"))
        # Two-way field + comment sync, people mapping (table via create_all), auto-send.
        await conn.execute(text("ALTER TABLE jira_connection ADD COLUMN IF NOT EXISTS auto_send VARCHAR NOT NULL DEFAULT 'off'"))
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS jira_snapshot JSONB"))
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS jira_error TEXT"))
        for column in ("jira_comment_id VARCHAR", "author_name VARCHAR", "source VARCHAR"):
            await conn.execute(text(f"ALTER TABLE task_comments ADD COLUMN IF NOT EXISTS {column}"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_task_comments_jira_id ON task_comments(jira_comment_id)"))
        # Word-by-word highlighting during playback.
        await conn.execute(text("ALTER TABLE transcript_segments ADD COLUMN IF NOT EXISTS word_times JSONB"))
        # Vocabulary: where an auto/suggested entry came from (known_people,
        # term_suggestions come from create_all).
        await conn.execute(text("ALTER TABLE term_corrections ADD COLUMN IF NOT EXISTS note VARCHAR"))
        # Privacy: confidential meetings, and tasks held from owners who weren't in the meeting.
        for column in ("confidential BOOLEAN NOT NULL DEFAULT false", "confidential_source VARCHAR", "confidential_reason VARCHAR"):
            await conn.execute(text(f"ALTER TABLE meetings ADD COLUMN IF NOT EXISTS {column}"))
        for column in ("owner_shared_at TIMESTAMPTZ", "owner_kept_private_at TIMESTAMPTZ"):
            await conn.execute(text(f"ALTER TABLE tasks ADD COLUMN IF NOT EXISTS {column}"))
        # Meeting email outside INTERNAL_EMAIL_DOMAINS waits for a deliberate share.
        await conn.execute(text("ALTER TABLE meeting_attendees ADD COLUMN IF NOT EXISTS shared_at TIMESTAMPTZ"))
        # A reassigned task kept its previous owner's account (the owner name
        # changed, owner_user_id didn't), so it still showed as theirs. Re-link
        # every task whose account no longer matches its owner name: to the one
        # active account with that full name or email, else to nobody.
        await conn.execute(text("""
            UPDATE tasks t SET owner_user_id = (
                SELECT CASE WHEN count(*) = 1 THEN min(u.id::text)::uuid END FROM users u
                WHERE u.status = 'active' AND btrim(t.owner) <> ''
                  AND (lower(btrim(u.name)) = lower(btrim(t.owner)) OR lower(u.email) = lower(btrim(t.owner)))
            )
            FROM users cur
            WHERE cur.id = t.owner_user_id
              AND lower(btrim(coalesce(t.owner, ''))) NOT IN (
                  lower(btrim(coalesce(cur.name, ''))), lower(cur.email),
                  lower(split_part(btrim(coalesce(cur.name, '')), ' ', 1)), lower(split_part(cur.email, '@', 1))
              )
        """))
    print("Tables created.")


if __name__ == "__main__":
    asyncio.run(main())
