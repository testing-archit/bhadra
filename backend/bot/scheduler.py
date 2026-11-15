"""The notetaker's main loop — the Fireflies "invite fred@fireflies.ai" model.

Anyone adds the notetaker's Google account to a calendar event that has a
Meet link. Google drops the invite on the notetaker's own calendar; this loop
polls that calendar, RSVPs yes, and a minute before each meeting starts
launches meeting_session.py to join it. No one has to connect their own
calendar or install anything.
"""

import json
import logging
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import config
import uploader
from google_calendar import GoogleCalendar, parse_event
from teams_dom import loggable_url

log = logging.getLogger("scheduler")

ACCEPT_EVERY_SECONDS = 600
ACCEPT_LOOKAHEAD = timedelta(days=14)
RETRY_UPLOADS_EVERY_SECONDS = 600
FORGET_AFTER = timedelta(days=3)
CALENDAR_SETTINGS = ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_CALENDAR_REFRESH_TOKEN")


class Scheduler:
    def __init__(self) -> None:
        # Without calendar credentials the bot still serves "add the
        # notetaker to this link" requests from Wilco; it just can't see
        # calendar invites.
        self.calendar: GoogleCalendar | None = None
        if all(config._env(name) for name in CALENDAR_SETTINGS):
            self.calendar = GoogleCalendar()
        else:
            log.warning("Calendar credentials not set (%s) — serving meeting-link requests only", ", ".join(CALENDAR_SETTINGS))
        # key -> ISO time it was dispatched. Persisted so a restart mid-meeting
        # does not send a second bot into the same call.
        self.dispatched: dict[str, str] = {}
        self.running: dict[str, tuple[subprocess.Popen, str]] = {}  # key -> (process, meet code)
        self.stopping = False
        self.last_accept = 0.0
        self.last_retry = 0.0
        self.last_calendar = 0.0
        self._load()

    def _load(self) -> None:
        if config.SCHEDULER_STATE_PATH.exists():
            self.dispatched = json.loads(config.SCHEDULER_STATE_PATH.read_text()).get("dispatched", {})

    def _save(self) -> None:
        cutoff = datetime.now(UTC) - FORGET_AFTER
        self.dispatched = {
            k: v for k, v in self.dispatched.items() if datetime.fromisoformat(v) > cutoff
        }
        tmp = config.SCHEDULER_STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"dispatched": self.dispatched}, indent=2))
        tmp.replace(config.SCHEDULER_STATE_PATH)

    def reap(self) -> None:
        for key, (process, code) in list(self.running.items()):
            if process.poll() is not None:
                log.info("Session for %s finished (exit %s)", code, process.returncode)
                del self.running[key]

    def accept_invites(self) -> None:
        if self.calendar is None:
            return
        now = datetime.now(UTC)
        for event in self.calendar.raw_events(now, now + ACCEPT_LOOKAHEAD):
            meeting = parse_event(event)
            if meeting and meeting.response_status == "needsAction":
                try:
                    self.calendar.accept(event)
                    log.info("Accepted invite: %s (%s)", meeting.title or meeting.event_id, meeting.start)
                except Exception as error:
                    log.warning("Could not accept %s: %s", meeting.event_id, error)

    def dispatch_due(self) -> None:
        """Hand invites that are about to start to Wilco's queue rather than
        joining directly. One queue means one bot per meeting: if a
        colleague's linked calendar or a pasted link already covers this call,
        the backend just adds the organizer to that visit. The bot then picks
        it up through the normal claim within a few seconds."""
        if self.calendar is None:
            return
        now = datetime.now(UTC)
        meetings = self.calendar.meetings(now, now + timedelta(seconds=config.JOIN_EARLY_SECONDS + config.POLL_SECONDS))
        for meeting in meetings:
            if meeting.key in self.dispatched or meeting.end <= now:
                continue
            if meeting.start - timedelta(seconds=config.JOIN_EARLY_SECONDS) > now:
                continue
            try:
                result = uploader.queue_invite(meeting)
            except Exception as error:
                log.warning("Could not queue %s: %s — will retry", meeting.meet_code, error)
                continue
            self.dispatched[meeting.key] = now.isoformat()
            log.info("Queued invite %s (%s): %s", meeting.title or meeting.event_id, meeting.meet_code, result.get("status"))
        self._save()

    def launch(self, meeting) -> None:
        self.launch_job(meeting.to_job(), key=meeting.key, code=meeting.meet_code)

    def launch_job(self, job: dict, *, key: str, code: str) -> None:
        jobs = config.STATE_DIR / "jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        job_path = jobs / f"{code}-{int(time.time())}.json"
        job_path.write_text(json.dumps(job, indent=2))
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).parent / "meeting_session.py"), "--job", str(job_path)]
        )
        self.running[key] = (process, code)
        self.dispatched[key] = datetime.now(UTC).isoformat()
        log.info("Joining %r at %s (pid %d)", job.get("title"), loggable_url(job["meet_url"]), process.pid)

    def dispatch_capture_requests(self) -> None:
        """Meetings someone pasted into Wilco's "Add notetaker" box. The
        claim call doubles as this bot's heartbeat, so it runs every tick
        even at capacity (claiming nothing)."""
        capacity = max(0, config.MAX_CONCURRENT_MEETINGS - len(self.running))
        try:
            jobs = uploader.claim_capture_requests(capacity, active=len(self.running))
        except Exception as error:
            log.warning("Could not poll capture requests: %s", error)
            return
        running_codes = {code for _, code in self.running.values()}
        for job in jobs:
            code = job.get("meeting_code") or job["meet_url"].rsplit("/", 1)[-1]
            if code in running_codes:
                uploader.report_capture_event(
                    job["capture_request_id"], "failed", "The notetaker is already in this meeting from a calendar invite"
                )
                continue
            self.launch_job(job, key=f"capture:{job['capture_request_id']}", code=code)
            running_codes.add(code)

    def request_stop(self, signum, _frame) -> None:
        """`docker stop` (a deploy restarting an idle notetaker). As PID 1
        with no handler, SIGTERM was ignored and every restart waited out the
        whole stop timeout. Idle: exit now. In a meeting: take no new work and
        let the recording finish (deploys only stop an idle notetaker; anyone
        else stopping it gets the same timeout as before)."""
        self.stopping = True
        self.reap()
        if not self.running:
            log.info("Stopping (signal %s)", signum)
            sys.exit(0)
        log.warning("Asked to stop during %d meeting(s); taking no new work", len(self.running))

    def tick(self) -> None:
        self.reap()
        if self.stopping:
            if not self.running:
                sys.exit(0)
            return
        self.dispatch_capture_requests()
        # Calendar work is slow-moving and rate-limited; it keeps its own pace
        # while the capture-request check above runs every few seconds.
        if time.time() - self.last_calendar < config.POLL_SECONDS:
            return
        self.last_calendar = time.time()
        if time.time() - self.last_accept > ACCEPT_EVERY_SECONDS:
            self.last_accept = time.time()
            self.accept_invites()
        self.dispatch_due()
        if not self.running and time.time() - self.last_retry > RETRY_UPLOADS_EVERY_SECONDS:
            # Only while idle: a session uploads its own meeting on exit, and
            # retrying a folder it is still writing would double-post it.
            self.last_retry = time.time()
            uploader.retry_pending()

    def run_forever(self) -> None:
        if self.calendar is not None:
            log.info("Watching %s's calendar every %ds", config.NOTETAKER_EMAIL, config.POLL_SECONDS)
        while True:
            try:
                self.tick()
            except Exception:
                log.exception("Scheduler tick failed; will retry")
            time.sleep(config.CAPTURE_POLL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [scheduler] %(levelname)s %(message)s")
    # One request every few seconds would bury the useful lines.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    scheduler = Scheduler()
    signal.signal(signal.SIGTERM, scheduler.request_stop)
    scheduler.run_forever()
