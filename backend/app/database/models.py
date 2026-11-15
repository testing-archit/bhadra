import uuid
from datetime import date, datetime

from sqlalchemy import ARRAY, TIMESTAMP, Boolean, Column, Date, Float, ForeignKey, Index, Integer, String, Table, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base


meeting_projects = Table(
    "meeting_projects",
    Base.metadata,
    Column("meeting_id", UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True),
    Column("project_id", UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", TIMESTAMP(timezone=True), server_default=func.now(), nullable=False),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    google_sub: Mapped[str | None] = mapped_column(String, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, nullable=False, server_default="member")
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="active")
    job_title: Mapped[str | None] = mapped_column(String)
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL")
    )
    department: Mapped[str | None] = mapped_column(String)
    google_sheets_spreadsheet_id: Mapped[str | None] = mapped_column(String)
    google_sheets_tasks_tab: Mapped[str] = mapped_column(String, nullable=False, server_default="Tasks")
    google_sheets_notes_tab: Mapped[str] = mapped_column(String, nullable=False, server_default="Meeting Notes")
    # {category: bool}; missing categories use email_service.DEFAULT_PREFS.
    email_prefs: Mapped[dict | None] = mapped_column(JSONB)
    # Tokens issued before this moment are refused — set on a password reset
    # or change, so a stolen session can't outlive it.
    sessions_valid_after: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class VoiceProfile(Base):
    """Encrypted speaker embedding from a user's explicit voice setup."""
    __tablename__ = "voice_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    embedding_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    confirmed_samples: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class VoiceProfileConfirmation(Base):
    __tablename__ = "voice_profile_confirmations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True
    )
    speaker_key: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AdminAuditEvent(Base):
    __tablename__ = "admin_audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    target_type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        UniqueConstraint("user_id", "client_meeting_id", name="uq_meeting_client_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String, nullable=False)
    date: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    transcript: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    department: Mapped[str | None] = mapped_column(String)
    # The Chrome extension's own id for the recording this meeting came from.
    # Unique per user so a retried ingest — the MV3 service worker can be
    # evicted mid-request and re-run finalize five minutes later — resolves to
    # the meeting that was already created instead of duplicating it.
    client_meeting_id: Mapped[str | None] = mapped_column(String)
    # The calendar organizer, when they have a Charcha account. Together with
    # the owner (user_id) and Charcha admins, they decide who else may read it.
    organizer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # Recurring meetings (daily sync-ups, weekly reviews) share a series key:
    # "gcal:<recurringEventId>" from a calendar, else "meet:<code>".
    meeting_code: Mapped[str | None] = mapped_column(String)
    series_key: Mapped[str | None] = mapped_column(String, index=True)
    # Gemini's check of the previous occurrence's open tasks against this
    # meeting's transcript — see series_service.review_carry_over.
    series_review: Mapped[dict | None] = mapped_column(JSONB)
    summary_verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    summary_verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    # NULL until an attendee copies the external share link — the endpoint
    # that hands out the link is the only place this ever gets set.
    share_token: Mapped[str | None] = mapped_column(String, unique=True)
    # Confidential: only the recorder, the organizer and granted attendees
    # can open it — no admin exemption, no Jira, no share link, and none of
    # its tasks reach anyone outside it unless a manager sends one. Marked by
    # a person or by the notes AI (confidential_source "ai" | "manual"; a
    # person's choice, either way, is never overruled by a later AI pass).
    confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    confidential_source: Mapped[str | None] = mapped_column(String)
    confidential_reason: Mapped[str | None] = mapped_column(String)
    # Where the meeting came from: extension | upload | paste | record | bot |
    # capture. NULL on rows that predate the column.
    source: Mapped[str | None] = mapped_column(String)
    # Which extraction template the current insights were generated with.
    template: Mapped[str] = mapped_column(String, nullable=False, server_default="general")
    # Bumped on every human transcript correction. Insights generated from an
    # older revision are stale: `insights_revision < transcript_revision`.
    transcript_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    insights_revision: Mapped[int | None] = mapped_column(Integer)

    tasks: Mapped[list["MeetingTask"]] = relationship(back_populates="meeting", cascade="all, delete-orphan")
    decisions: Mapped[list["Decision"]] = relationship(back_populates="meeting", cascade="all, delete-orphan")
    risks: Mapped[list["Risk"]] = relationship(back_populates="meeting", cascade="all, delete-orphan")
    projects: Mapped[list["Project"]] = relationship(
        secondary=meeting_projects, back_populates="meetings"
    )


class MeetingBoard(Base):
    """Editable meeting canvas. A live capture can own it before a meeting exists."""

    __tablename__ = "meeting_boards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), unique=True, index=True
    )
    capture_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capture_requests.id", ondelete="SET NULL"), unique=True, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False, server_default="Meeting board")
    nodes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    edges: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    ai_cursor_seconds: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    last_ai_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MeetingBoardRevision(Base):
    """One immutable board snapshot for history and conflict recovery."""

    __tablename__ = "meeting_board_revisions"
    __table_args__ = (UniqueConstraint("board_id", "version", name="uq_board_revision_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    board_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_boards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    nodes: Mapped[list] = mapped_column(JSONB, nullable=False)
    edges: Mapped[list] = mapped_column(JSONB, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class LiveCaption(Base):
    """A finalized caption chunk sent by the bot while a call is happening."""

    __tablename__ = "meeting_live_captions"
    __table_args__ = (UniqueConstraint("capture_request_id", "seq", name="uq_live_caption_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    capture_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capture_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class Project(Base):
    """A cross-meeting entity that tasks/decisions/risks can be tagged with,
    so 'show me everything tied to Project X' works across the whole
    company memory instead of per-meeting. Resolved by case-insensitive
    exact name match at ingest time (see meetings.py) — no fuzzy matching,
    so "the Academy thing" vs "Bhadra Academy" won't auto-merge yet."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    department: Mapped[str | None] = mapped_column(String)
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    tasks: Mapped[list["MeetingTask"]] = relationship(back_populates="project")
    decisions: Mapped[list["Decision"]] = relationship(back_populates="project")
    risks: Mapped[list["Risk"]] = relationship(back_populates="project")
    meetings: Mapped[list["Meeting"]] = relationship(
        secondary=meeting_projects, back_populates="projects"
    )


class MeetingTask(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    meeting_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    owner: Mapped[str | None] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    deadline: Mapped[str | None] = mapped_column(String)
    # The AI-extracted phrase as said ("Friday") is kept in `deadline` for
    # display; `due_date` is the same due date resolved to a real calendar
    # date (using the meeting's own date as the anchor for relative phrases)
    # so it can actually be sorted, filtered, and used for reminders.
    due_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    # The owner *as stated* stays in `owner`; this is set only when that name
    # resolves unambiguously to one internal attendee of the meeting.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # An owner who can't open the meeting doesn't see the task until a
    # manager sends it (owner_shared_at) — then only the task, never the
    # meeting. owner_kept_private_at records "keep it private". See
    # app/services/privacy_service.py.
    owner_shared_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    owner_kept_private_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    # Grounding for AI-extracted items: [{segment_id, seq, start_ms, excerpt,
    # verified}] — see app/services/insight_service.validate_evidence.
    evidence: Mapped[list[dict] | None] = mapped_column(JSONB)
    # Review flags the extractor or validator raised, e.g. "evidence_missing",
    # "due_date_ambiguous". Empty/NULL means nothing to flag.
    ai_flags: Mapped[list[str] | None] = mapped_column(JSONB)
    # "ai" for extracted items, "manual" for ones a person created. Insight
    # regeneration never touches manual or reviewed items.
    origin: Mapped[str] = mapped_column(String, nullable=False, server_default="ai")
    # Set once the task has been sent to Jira (app/services/jira_service.py).
    # Status then syncs both ways; jira_status is Jira's own status name.
    jira_issue_key: Mapped[str | None] = mapped_column(String, unique=True)
    jira_status: Mapped[str | None] = mapped_column(String)
    jira_synced_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    # The issue's fields as of the last sync ({summary, assignee, duedate,
    # priority, category}); a field that differs from it on the next poll was
    # changed in Jira. See jira_service.apply_issue.
    jira_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    # Why the last push to Jira failed, shown on the task; None when fine.
    jira_error: Mapped[str | None] = mapped_column(Text)

    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE")
    )
    verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    meeting: Mapped["Meeting"] = relationship(back_populates="tasks")
    project: Mapped["Project | None"] = relationship(back_populates="tasks")


class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Comments are mirrored with Jira: the issue comment's id (either way),
    # and for ones written in Jira the Jira author's name.
    jira_comment_id: Mapped[str | None] = mapped_column(String, unique=True)
    author_name: Mapped[str | None] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(String)  # None (Charcha) | "jira"
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class TaskHistory(Base):
    """One row per changed field on a task PATCH — a lightweight audit log,
    not a full snapshot history."""
    __tablename__ = "task_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"))
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    field: Mapped[str] = mapped_column(String, nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    # None for a Charcha user's edit; "jira" when the Jira sync changed it.
    source: Mapped[str | None] = mapped_column(String)
    changed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class TaskLink(Base):
    """Directed link from one task to another, e.g. task_id 'blocks' linked_task_id."""
    __tablename__ = "task_links"
    __table_args__ = (UniqueConstraint("task_id", "linked_task_id", "link_type", name="uq_task_link"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"))
    linked_task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"))
    link_type: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str | None] = mapped_column(String)
    read_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    meeting_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    alternatives: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    participants: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    conflict_note: Mapped[str | None] = mapped_column(Text)
    # Grounding for AI-extracted items: [{segment_id, seq, start_ms, excerpt,
    # verified}] — see app/services/insight_service.validate_evidence.
    evidence: Mapped[list[dict] | None] = mapped_column(JSONB)
    # Review flags the extractor or validator raised, e.g. "evidence_missing",
    # "due_date_ambiguous". Empty/NULL means nothing to flag.
    ai_flags: Mapped[list[str] | None] = mapped_column(JSONB)
    # "ai" for extracted items, "manual" for ones a person created. Insight
    # regeneration never touches manual or reviewed items.
    origin: Mapped[str] = mapped_column(String, nullable=False, server_default="ai")
    verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    meeting: Mapped["Meeting"] = relationship(back_populates="decisions")
    project: Mapped["Project | None"] = relationship(back_populates="decisions")


class Risk(Base):
    __tablename__ = "risks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    meeting_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str | None] = mapped_column(String)
    # Grounding for AI-extracted items: [{segment_id, seq, start_ms, excerpt,
    # verified}] — see app/services/insight_service.validate_evidence.
    evidence: Mapped[list[dict] | None] = mapped_column(JSONB)
    # Review flags the extractor or validator raised, e.g. "evidence_missing",
    # "due_date_ambiguous". Empty/NULL means nothing to flag.
    ai_flags: Mapped[list[str] | None] = mapped_column(JSONB)
    # "ai" for extracted items, "manual" for ones a person created. Insight
    # regeneration never touches manual or reviewed items.
    origin: Mapped[str] = mapped_column(String, nullable=False, server_default="ai")
    verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    meeting: Mapped["Meeting"] = relationship(back_populates="risks")
    project: Mapped["Project | None"] = relationship(back_populates="risks")


class Trace(Base):
    __tablename__ = "traces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("meetings.id"))
    meeting_title: Mapped[str | None] = mapped_column(String)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    # Column name kept as "whisper_requests" to match the existing prod DB
    # column (avoids a migration) — the attribute name is provider-neutral
    # since transcription now goes through Prisma, not Whisper.
    transcription_requests: Mapped[int | None] = mapped_column("whisper_requests", Integer)
    # Physical column names are retained for compatibility with the existing
    # database; application and API terminology is provider-neutral.
    ai_input_tokens: Mapped[int | None] = mapped_column("claude_input_tokens", Integer)
    ai_output_tokens: Mapped[int | None] = mapped_column("claude_output_tokens", Integer)
    ai_cache_hits: Mapped[int | None] = mapped_column("claude_cache_hits", Integer)
    tasks_found: Mapped[int | None] = mapped_column(Integer)
    decisions_found: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class RecordingSession(Base):
    __tablename__ = "recording_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String, nullable=False)
    meeting_type: Mapped[str] = mapped_column(String, nullable=False, default="physical")
    language: Mapped[str] = mapped_column(String, nullable=False, default="hinglish")
    participants: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    # Structured form of `participants`: one entry per attendee, carrying the
    # Charcha user_id when the attendee has an account and NULL when they are an
    # external guest. `participants` keeps only display names, which is all the
    # speaker-count and PDF code needs; this is what becomes MeetingAttendee
    # rows once the recording is linked to a meeting.
    attendees: Mapped[list[dict] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String, nullable=False, default="recording")
    mime_type: Mapped[str | None] = mapped_column(String)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    total_bytes: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class MeetingInsight(Base):
    __tablename__ = "meeting_insights"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True
    )
    key_topics: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    open_questions: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    highlights: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    next_steps: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    speaker_activity: Mapped[list[dict] | None] = mapped_column(JSONB)
    overview: Mapped[str | None] = mapped_column(Text)
    # [{title, summary, evidence}] — timestamped discussion sections.
    sections: Mapped[list[dict] | None] = mapped_column(JSONB)
    # [{heading, items: [{text, evidence}]}] — template-specific output.
    template_sections: Mapped[list[dict] | None] = mapped_column(JSONB)
    # A draft only — never sent anywhere automatically.
    follow_up_draft: Mapped[str | None] = mapped_column(Text)


class MemoryConversation(Base):
    __tablename__ = "memory_conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    # An explicit multi-meeting scope ("ask across these meetings"). Access to
    # every id is rechecked on each question, never trusted from storage.
    scope_meeting_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["MemoryMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="MemoryMessage.created_at"
    )


class MemoryMessage(Base):
    __tablename__ = "memory_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list[dict] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    conversation: Mapped["MemoryConversation"] = relationship(back_populates="messages")


# --- Bhadra Policy chatbot ---
# Deliberately its own tables, own service, own route, own Pinecone
# namespace — kept fully separate from the company-memory/meetings feature
# rather than reusing it, per explicit product requirement.


class PolicyConversation(Base):
    __tablename__ = "policy_conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["PolicyMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="PolicyMessage.created_at"
    )


class PolicyMessage(Base):
    __tablename__ = "policy_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String, nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list[dict] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    conversation: Mapped["PolicyConversation"] = relationship(back_populates="messages")


class MeetingAttendee(Base):
    """Who was in the meeting — and therefore who is allowed to read it.

    Access is attendee-based, not department-based: a row here (or owning the
    meeting) is what grants a user visibility of the meeting and everything
    derived from it. Two kinds of row live in this table:

    * internal — `user_id` points at a Charcha account. These grant access.
    * external — `user_id` is NULL. A guest, client, or vendor who was in the
      room but has no Charcha login. Recorded for the meeting record only;
      they can never sign in, so they grant nothing.
    """

    __tablename__ = "meeting_attendees"
    __table_args__ = (
        UniqueConstraint("meeting_id", "user_id", name="uq_meeting_attendee_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str | None] = mapped_column(String)
    # "internal" | "external" — derivable from user_id, stored explicitly so an
    # external guest who later gets a Charcha account is not silently upgraded.
    kind: Mapped[str] = mapped_column(String, nullable=False, server_default="internal")
    # "manual" | "meet" | "recorder" — where this attendee came from, so a
    # name auto-matched from Google Meet captions can be told apart from one a
    # person deliberately added.
    source: Mapped[str] = mapped_column(String, nullable=False, server_default="manual")
    # "granted" | "pending". Only granted rows let a colleague read the
    # meeting. People the notetaker saw in the call who were not on the
    # invite are recorded as "pending" until the meeting's organizer or a
    # Charcha admin shares it with them — see attendee_service.
    access: Mapped[str] = mapped_column(String, nullable=False, server_default="granted")
    # When the recorder, organizer or an admin deliberately shared the meeting
    # with this person in Charcha (share, grant, or the attendee editor) — not
    # set by a calendar invite or by being heard in the call. Someone outside
    # INTERNAL_EMAIL_DOMAINS is only emailed about the meeting once it's set.
    shared_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


# --- Meeting Assistant workspace ---


class TranscriptSegment(Base):
    """One speaker turn of a meeting transcript.

    Segments are the authoritative transcript once they exist —
    `Meeting.transcript` is re-rendered from them after every correction.
    `original_text` keeps the ASR (or pasted) text exactly as first stored, so
    an edit can always be compared with or reverted to what was heard.
    """

    __tablename__ = "transcript_segments"
    __table_args__ = (UniqueConstraint("meeting_id", "seq", name="uq_transcript_segment_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    # Diarizer speaker number as a string ("0", "1"), a name the transcript
    # itself stated ("Priya"), or "" when nothing identifies the speaker.
    speaker_key: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    # Display name. NULL means "use the generic label" (Speaker N / Unknown).
    speaker_label: Mapped[str | None] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)
    # Only ever a confidence the transcription provider actually returned.
    confidence: Mapped[float | None] = mapped_column(Float)
    # [[start_ms, end_ms], ...] — one per space-separated word of the ASR
    # text, for word-by-word highlighting. Ignored by the player once the text
    # was corrected and no longer has the same number of words.
    word_times: Mapped[list | None] = mapped_column(JSONB)
    language: Mapped[str | None] = mapped_column(String)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    edited_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    edited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class TranscriptEdit(Base):
    """Edit history for transcript corrections and speaker renames."""

    __tablename__ = "transcript_edits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcript_segments.id", ondelete="SET NULL")
    )
    field: Mapped[str] = mapped_column(String, nullable=False)  # "text" | "speaker"
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    transcript_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    edited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class TermCorrection(Base):
    """Company vocabulary for transcription (see vocabulary_service):
    a rule "heard as `wrong`, actually `right`" ("Sky Tech" → "Sky Lattice"),
    or with no `wrong` a keyword Prisma should listen for. Rules come from
    people's edits (`learned`) or are added on the Vocabulary page (`manual`)."""

    __tablename__ = "term_corrections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    wrong: Mapped[str | None] = mapped_column(String, unique=True)
    right: Mapped[str] = mapped_column(String, nullable=False)
    # learned (someone's edit) | manual (Vocabulary page) | suggested (a
    # suggestion confirmed, or applied after enough meetings) | auto (a
    # keyword picked up from projects, Jira or meeting titles).
    source: Mapped[str] = mapped_column(String, nullable=False, server_default="learned")
    # Where an auto/suggested entry came from ("Jira project", "Heard in 3 meetings").
    note: Mapped[str | None] = mapped_column(String)
    # How many separate edits taught it, and how often it has fixed text since.
    times_confirmed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    times_applied: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    source_meeting_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="SET NULL"))
    # Switched off on the Vocabulary page (or undone by the reverse correction).
    disabled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())


class KnownPerson(Base):
    """Someone without a Charcha account whose name transcription should get
    right — a client, vendor or regular guest (Vocabulary → Teammates).
    Accounts need no row here: their names are used automatically."""

    __tablename__ = "known_people"
    __table_args__ = (Index("uq_known_people_name", func.lower(text("name")), unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str | None] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class TermSuggestion(Base):
    """A probable mishearing Charcha noticed on its own (vocabulary_service.
    learn_from_meeting): a word in a transcript that sounds like an invitee's
    name but isn't spelled like it, optionally backed by Meet's captions.
    Someone accepts or dismisses it on the Vocabulary page; heard in enough
    meetings, it is applied without waiting."""

    __tablename__ = "term_suggestions"
    __table_args__ = (Index("uq_term_suggestion", func.lower(text("wrong")), func.lower(text("\"right\"")), unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    wrong: Mapped[str] = mapped_column(String, nullable=False)
    right: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False, server_default="attendee")  # attendee | captions
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")  # pending | accepted | dismissed | auto
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Distinct meetings it was heard in (strings, so reprocessing never double counts).
    meeting_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    last_meeting_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="SET NULL"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())


class ProcessingStage(Base):
    """Durable per-stage pipeline state, so a failed stage can be retried on
    its own without repeating (or re-paying for) the stages that succeeded."""

    __tablename__ = "meeting_processing_stages"
    __table_args__ = (UniqueConstraint("meeting_id", "stage", name="uq_processing_stage"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # transcription | extraction | indexing | audio | diarization
    stage: Mapped[str] = mapped_column(String, nullable=False)
    # pending | running | succeeded | failed | skipped
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InsightRun(Base):
    """One generation of a meeting's AI notes — what model, prompt and
    transcript revision produced them, and what it cost."""

    __tablename__ = "insight_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transcript_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    template: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # running | succeeded | failed
    error: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    evidence_checked: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    evidence_rejected: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class MeetingComment(Base):
    __tablename__ = "meeting_comments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    # Anchor. The segment may be replaced by a re-diarization, so the time and
    # quoted text are kept alongside it to keep the comment meaningful.
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcript_segments.id", ondelete="SET NULL")
    )
    start_ms: Mapped[int | None] = mapped_column(Integer)
    quote: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class MeetingBookmark(Base):
    """A bookmark or soundbite: a bounded playback range, not a clipped file."""

    __tablename__ = "meeting_bookmarks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcript_segments.id", ondelete="SET NULL")
    )
    label: Mapped[str] = mapped_column(String, nullable=False)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


CAPTURE_ACTIVE_STATUSES = ("requested", "joining", "waiting_for_admission", "capturing")


class CaptureRequest(Base):
    """A request to send the notetaker bot into a live meeting by URL.

    Status only moves on evidence the bot reports — a request being accepted
    here means nothing has joined yet. At most one *active* request per Meet
    code exists (partial unique index), so a double click, a retried request
    or two colleagues pasting the same link never sends two bots.
    """

    __tablename__ = "capture_requests"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_capture_idempotency"),
        Index(
            "uq_capture_active_meeting",
            "meeting_code",
            unique=True,
            postgresql_where=text("status IN ('requested','joining','waiting_for_admission','capturing')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)  # google_meet | microsoft_teams
    meeting_url: Mapped[str] = mapped_column(String, nullable=False)
    meeting_code: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str | None] = mapped_column(String)
    template: Mapped[str] = mapped_column(String, nullable=False, server_default="general")
    # requested | joining | waiting_for_admission | capturing | stopped |
    # completed | denied | timed_out | failed | cancelled
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="requested")
    status_detail: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String)
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="SET NULL"))
    consent_acknowledged_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    stop_requested_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_event_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    # "link" (pasted / extension) | "calendar" (a linked Google Calendar) |
    # "invite" (the notetaker's own address was invited to the event).
    source: Mapped[str] = mapped_column(String, nullable=False, server_default="link")
    # Calendar invitees ({"email", "name"}); they get access to the notes.
    invitees: Mapped[list | None] = mapped_column(JSONB)
    organizer_email: Mapped[str | None] = mapped_column(String)
    scheduled_start: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    scheduled_end: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    series_key: Mapped[str | None] = mapped_column(String)
    # Tasks someone added from the call's chat ("Charcha, add task: ..."),
    # held here until the meeting exists, then created as origin="live".
    live_tasks: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CaptureSubscriber(Base):
    """Everyone who wants the notes from one notetaker visit.

    A meeting is recorded once, however many colleagues ask for it: the first
    request creates the CaptureRequest, every later one (a colleague pasting
    the same link, several linked calendars holding the same event) just adds
    a row here. All of them can read the result; the bot only leaves early
    when the last of them stops it.
    """

    __tablename__ = "capture_subscribers"
    __table_args__ = (UniqueConstraint("capture_request_id", "user_id", name="uq_capture_subscriber"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    capture_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capture_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # "link" | "calendar" | "invite"
    source: Mapped[str] = mapped_column(String, nullable=False, server_default="link")
    # Set when this person pressed Stop; they no longer hold the bot in the call.
    released_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class CalendarConnection(Base):
    """A person's linked Google Calendar. The refresh token is encrypted at
    rest (app/services/secret_box.py) and never leaves the backend."""

    __tablename__ = "calendar_connections"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    google_email: Mapped[str] = mapped_column(String, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # "all" — every event with a Meet link I haven't declined;
    # "organized" — only events I organize; "manual" — only events I switch on.
    auto_join: Mapped[str] = mapped_column(String, nullable=False, server_default="all")
    # "active" | "error" (Google refused the token; reconnect needed)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="active")
    last_error: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    # Google push channel (events.watch): Google calls /api/calendar/push the
    # moment this calendar changes, so a meeting added two minutes before it
    # starts is still joined. NULL / expired falls back to fast polling.
    watch_channel_id: Mapped[str | None] = mapped_column(String, unique=True)
    watch_resource_id: Mapped[str | None] = mapped_column(String)
    watch_token: Mapped[str | None] = mapped_column(String)
    watch_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    watch_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class CalendarEvent(Base):
    """An upcoming event from a linked calendar, kept so people can see what
    the notetaker will join and switch individual meetings on or off."""

    __tablename__ = "calendar_events"
    __table_args__ = (UniqueConstraint("user_id", "google_event_id", name="uq_calendar_event"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    google_event_id: Mapped[str] = mapped_column(String, nullable=False)
    # Same for every occurrence of a recurring event.
    recurring_event_id: Mapped[str | None] = mapped_column(String)
    title: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    start_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, index=True)
    end_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    meeting_url: Mapped[str | None] = mapped_column(String)
    meeting_code: Mapped[str | None] = mapped_column(String, index=True)
    # Zoom/Teams/etc. link the notetaker doesn't auto-join from a calendar, shown
    # so it isn't a mystery. (A Teams link can still be pasted in to send it.)
    unsupported_platform: Mapped[str | None] = mapped_column(String)
    organizer_email: Mapped[str | None] = mapped_column(String)
    is_organizer: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    invitees: Mapped[list | None] = mapped_column(JSONB)
    # None follows the connection's auto_join rule; True/False is the
    # person's explicit choice for this one meeting.
    record_override: Mapped[bool | None] = mapped_column(Boolean)
    capture_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capture_requests.id", ondelete="SET NULL")
    )
    cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # The automatic pre-meeting brief (see prep_service): {"status": "ready" |
    # "empty" | "failed", "text", "meetings", "open_tasks", "decisions",
    # "error"}. brief_generated_at is set once it has been attempted, so the
    # calendar loop pays for at most one brief per event and person.
    brief: Mapped[dict | None] = mapped_column(JSONB)
    brief_generated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CaptureEvent(Base):
    """Every lifecycle event the bot reported, deduplicated by its event id."""

    __tablename__ = "capture_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    capture_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capture_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_event_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    received_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class ServiceHeartbeat(Base):
    """Last time an out-of-process worker (the notetaker bot) checked in, so
    the UI can say "offline" instead of letting a request wait silently."""

    __tablename__ = "service_heartbeats"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB)


class AiUsageEvent(Base):
    """One paid AI call, priced when it happened (see usage_ledger)."""

    __tablename__ = "ai_usage_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)  # gemini | gnani
    feature: Mapped[str] = mapped_column(String, nullable=False, index=True)
    model: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cached_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    audio_seconds: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    usd_cost: Mapped[float] = mapped_column(Float, nullable=False)
    usd_to_inr: Mapped[float] = mapped_column(Float, nullable=False)
    inr_cost: Mapped[float] = mapped_column(Float, nullable=False)
    rate_source: Mapped[str | None] = mapped_column(String)
    rate_quoted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="SET NULL"))


class EmailOutbox(Base):
    """Every email Charcha sends, queued in the same transaction as the event
    that caused it and sent by email_service's loop. Rendered at send time, so
    it reflects the latest data and the person's current preferences."""

    __tablename__ = "email_outbox"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_email_dedupe"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    # Same key, same email: a retried job or a second trigger never sends twice.
    dedupe_key: Mapped[str | None] = mapped_column(String)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    # 0 = security (never held back by the daily cap) … 3 = digests.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")
    # queued | sent | skipped | failed
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="queued", index=True)
    to_email: Mapped[str | None] = mapped_column(String)
    subject: Mapped[str | None] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    provider_message_id: Mapped[str | None] = mapped_column(String)
    send_after: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), index=True)


class PasswordResetToken(Base):
    """A single-use link to set a password. Only the token's hash is stored."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # "reset" (forgot password) | "invite" (an admin created the account)
    purpose: Mapped[str] = mapped_column(String, nullable=False, server_default="reset")
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class JiraConnection(Base):
    """The company's one Jira Cloud connection (a single row, id=1). Either
    "oauth" — an admin clicked Connect with Jira (Atlassian OAuth 2.0 3LO;
    rotating refresh token) — or "token": a service account's email + API
    token. Secrets are encrypted at rest with secret_box. Issues are created
    by that account and assigned to the real person."""

    __tablename__ = "jira_connection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    auth_type: Mapped[str] = mapped_column(String, nullable=False, server_default="token")
    site_url: Mapped[str] = mapped_column(String, nullable=False)
    # token auth
    email: Mapped[str | None] = mapped_column(String)
    api_token_encrypted: Mapped[str | None] = mapped_column(Text)
    # oauth auth: the site's cloud id (API calls go through api.atlassian.com)
    cloud_id: Mapped[str | None] = mapped_column(String)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    # Jira project key for tasks whose Charcha project isn't mapped. Empty
    # right after Connect with Jira, until an admin picks one.
    default_project_key: Mapped[str | None] = mapped_column(String)
    # {charcha project id: Jira project key}
    project_map: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # When meeting notes are ready: "off" | "mapped" (tasks in a mapped Charcha
    # project) | "all" — send the open tasks to Jira without a click.
    auto_send: Mapped[str] = mapped_column(String, nullable=False, server_default="off")
    account_name: Mapped[str | None] = mapped_column(String)
    last_synced_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    connected_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class JiraUserLink(Base):
    """Which Jira user a Charcha person is, for assignees and comment authors.
    Jira Free usually hides emails, so links are matched by email or exact
    display name ("auto") and an admin can set or clear them ("manual"); a
    manual link is never overwritten by auto-matching."""

    __tablename__ = "jira_user_links"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # None with matched_by="manual" means "this person isn't in Jira".
    account_id: Mapped[str | None] = mapped_column(String, unique=True)
    display_name: Mapped[str | None] = mapped_column(String)
    matched_by: Mapped[str] = mapped_column(String, nullable=False)  # "email" | "name" | "manual"
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MeetingAgentJob(Base):
    """Durable current-meeting commands. Tool receipts commit with their effects."""
    __tablename__ = "meeting_agent_jobs"
    __table_args__ = (
        UniqueConstraint("capture_request_id", "command_id", name="uq_agent_capture_command"),
        Index("ix_agent_queue", "state", "created_at"),
        Index("uq_agent_running_capture", "capture_request_id", unique=True,
              postgresql_where=text("state = 'running'")),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capture_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capture_requests.id", ondelete="CASCADE"), nullable=False)
    command_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False, default="accepted")
    phase: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    plan: Mapped[list | None] = mapped_column(JSONB)
    receipts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    result: Mapped[dict | None] = mapped_column(JSONB)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    deadline_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
