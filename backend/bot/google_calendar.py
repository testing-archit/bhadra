"""Reads the notetaker account's own Google Calendar.

This is the whole "invite the bot" mechanism: when someone adds the
notetaker's address to an event, Google puts that event on the notetaker's
calendar, and the scheduler sees it here — no per-user calendar connection.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime

import httpx

import config

TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
# Meet also opens rooms at meet.google.com/meet/<code>; always return the plain room URL.
MEET_LINK_RE = re.compile(r"https://meet\.google\.com/(?:meet/)?([a-z]{3}-[a-z]{4}-[a-z]{3})")


def _room_url(match: re.Match) -> str:
    return f"https://meet.google.com/{match.group(1)}"


@dataclass
class CalendarMeeting:
    event_id: str
    title: str
    meet_url: str
    start: datetime
    end: datetime
    organizer_email: str | None
    attendees: list[dict] = field(default_factory=list)
    response_status: str = "needsAction"
    recurring_event_id: str | None = None

    @property
    def key(self) -> str:
        return f"{self.event_id}|{self.start.isoformat()}"

    @property
    def meet_code(self) -> str:
        return self.meet_url.rsplit("/", 1)[-1]

    def to_job(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_start": self.start.isoformat(),
            "event_end": self.end.isoformat(),
            "title": self.title,
            "meet_url": self.meet_url,
            "organizer_email": self.organizer_email,
            "attendees": self.attendees,
        }


def find_meet_link(event: dict) -> str | None:
    if MEET_LINK_RE.match(event.get("hangoutLink") or ""):
        return _room_url(MEET_LINK_RE.match(event["hangoutLink"]))
    for entry in (event.get("conferenceData") or {}).get("entryPoints") or []:
        if entry.get("entryPointType") == "video" and MEET_LINK_RE.match(entry.get("uri") or ""):
            return _room_url(MEET_LINK_RE.match(entry["uri"]))
    # Meetings pasted into the location or description by hand.
    for text in (event.get("location") or "", event.get("description") or ""):
        match = MEET_LINK_RE.search(text)
        if match:
            return _room_url(match)
    return None


def parse_event(event: dict) -> CalendarMeeting | None:
    """None for anything the bot should never join: cancelled or all-day
    events, events without a Meet link, and events it has declined."""
    if event.get("status") == "cancelled":
        return None
    start = (event.get("start") or {}).get("dateTime")
    end = (event.get("end") or {}).get("dateTime")
    meet_url = find_meet_link(event)
    if not start or not end or not meet_url:
        return None

    attendees = []
    response_status = "needsAction"
    for attendee in event.get("attendees") or []:
        email = (attendee.get("email") or "").lower()
        if attendee.get("self") or email == config.NOTETAKER_EMAIL:
            response_status = attendee.get("responseStatus") or response_status
            continue
        if attendee.get("resource"):  # meeting rooms
            continue
        attendees.append({"email": email or None, "name": attendee.get("displayName") or ""})
    if response_status == "declined":
        return None

    return CalendarMeeting(
        event_id=event["id"],
        title=(event.get("summary") or "").strip(),
        meet_url=meet_url,
        start=datetime.fromisoformat(start),
        end=datetime.fromisoformat(end),
        organizer_email=((event.get("organizer") or {}).get("email") or "").lower() or None,
        attendees=attendees,
        response_status=response_status,
        recurring_event_id=event.get("recurringEventId"),
    )


class GoogleCalendar:
    def __init__(self) -> None:
        self._client_id = config.require("GOOGLE_OAUTH_CLIENT_ID")
        self._client_secret = config.require("GOOGLE_OAUTH_CLIENT_SECRET")
        self._refresh_token = config.require("GOOGLE_CALENDAR_REFRESH_TOKEN")
        self._access_token = ""
        self._expires_at = 0.0
        self._http = httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))

    def _headers(self) -> dict:
        if time.time() > self._expires_at - 60:
            response = self._http.post(
                TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if not response.is_success:
                raise RuntimeError(f"Google token refresh failed {response.status_code}: {response.text[:300]}")
            payload = response.json()
            self._access_token = payload["access_token"]
            self._expires_at = time.time() + int(payload.get("expires_in", 3600))
        return {"Authorization": f"Bearer {self._access_token}"}

    def raw_events(self, time_min: datetime, time_max: datetime) -> list[dict]:
        """Every event overlapping [time_min, time_max], recurring meetings
        expanded into their individual occurrences."""
        events: list[dict] = []
        page_token = None
        while True:
            params = {
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": "250",
            }
            if page_token:
                params["pageToken"] = page_token
            response = self._http.get(EVENTS_URL, params=params, headers=self._headers())
            if not response.is_success:
                raise RuntimeError(f"Calendar list failed {response.status_code}: {response.text[:300]}")
            payload = response.json()
            events.extend(payload.get("items") or [])
            page_token = payload.get("nextPageToken")
            if not page_token:
                return events

    def meetings(self, time_min: datetime, time_max: datetime) -> list[CalendarMeeting]:
        return [m for m in (parse_event(e) for e in self.raw_events(time_min, time_max)) if m]

    def accept(self, event: dict) -> None:
        """RSVP "yes" so the organizer sees the notetaker is coming. An
        attendee may only change its own row, but the API still wants the
        whole attendee list back."""
        attendees = [
            {**a, "responseStatus": "accepted"} if a.get("self") else a
            for a in event.get("attendees") or []
        ]
        response = self._http.patch(
            f"{EVENTS_URL}/{event['id']}",
            params={"sendUpdates": "none"},
            json={"attendees": attendees},
            headers=self._headers(),
        )
        if not response.is_success:
            raise RuntimeError(f"Accept failed {response.status_code}: {response.text[:300]}")
