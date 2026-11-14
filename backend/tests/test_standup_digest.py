"""Stand-up digest: per-person updates/blockers/plans across a series."""

import datetime
import uuid

import pytest

from app.database.db import async_session
from app.database.models import Meeting, MeetingAttendee, MeetingInsight
from app.services.standup_service import UNATTRIBUTED, same_blocker, split_person
from tests.conftest import TEST_PREFIX, auth_headers


def test_split_person_prefers_the_field_then_a_spoken_prefix():
    assert split_person({"text": "Finished the API", "person": "Priya"}) == ("Priya", "Finished the API")
    assert split_person({"text": "Rahul: waiting on design"}) == ("Rahul", "waiting on design")
    assert split_person({"text": "Priya Sharma — shipping today"}) == ("Priya Sharma", "shipping today")
    # Lower-case lead-ins are sentences, not names.
    assert split_person({"text": "note: deploy froze"}) == (UNATTRIBUTED, "note: deploy froze")


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("Waiting on Acme's SSO metadata", "Still blocked on SSO metadata from Acme", True),
        ("Staging database is down", "staging DB down again", True),
        ("Staging database is down", "Production deploy is down", False),
        ("Staging database is down", "The staging database is still down", True),
        ("Waiting on design review for onboarding", "Laptop replacement hasn't arrived", False),
    ],
)
def test_same_blocker(a, b, same):
    assert same_blocker(a, b) is same


async def _occurrence(user, series: str, days_ago: int, sections: list[dict], template="standup") -> Meeting:
    async with async_session() as db:
        meeting = Meeting(
            user_id=user.id, title=f"{TEST_PREFIX}Daily stand-up", template=template, series_key=series,
            date=datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days_ago), transcript="x", summary="x",
        )
        db.add(meeting)
        await db.flush()
        db.add(MeetingInsight(meeting_id=meeting.id, template_sections=sections))
        await db.commit()
        await db.refresh(meeting)
        return meeting


def _sections(updates=(), blockers=(), plans=()):
    def items(values):
        return [{"text": text, "person": person, "evidence": []} for person, text in values]
    return [
        {"heading": "Updates", "items": items(updates)},
        {"heading": "Blockers", "items": items(blockers)},
        {"heading": "Plans", "items": items(plans)},
    ]


async def test_digest_groups_by_person_and_flags_repeated_blockers(client, member_user, other_member_user):
    series = f"meet:{TEST_PREFIX}{uuid.uuid4().hex[:8]}"
    oldest = await _occurrence(member_user, series, 9, _sections(updates=[("", "Rahul: set up CI")]))  # beyond the last five
    days = [6, 4, 3, 2]
    for day in days:
        await _occurrence(
            member_user, series, day,
            _sections(
                updates=[("Priya Sharma", f"Worked on pricing page day {day}")],
                blockers=[("Priya", "Waiting on Acme's SSO metadata") if day % 2 == 0 else ("Priya", "Still blocked on SSO metadata from Acme")],
                plans=[("Rahul", "Review onboarding flow")],
            ),
        )
    # A general meeting in the same series isn't a stand-up and is skipped.
    await _occurrence(member_user, series, 1, _sections(updates=[("Priya", "ignored")]), template="general")
    current = await _occurrence(
        member_user, series, 0,
        _sections(updates=[("Priya", "Pricing page shipped")], blockers=[("Rahul", "Laptop replacement hasn't arrived")]),
    )
    try:
        body = (await client.get(f"/api/meetings/{current.id}/series/standup", headers=auth_headers(member_user))).json()
        assert len(body["occurrences"]) == 5 and body["occurrences"][-1]["current"] is True
        assert str(oldest.id) not in [o["id"] for o in body["occurrences"]]
        names = [p["name"] for p in body["people"]]
        assert names == ["Priya Sharma", "Rahul"]  # "Priya" folded into her full name
        priya = body["people"][0]
        assert priya["blocker_count"] == 4 and len(priya["occurrences"]) == 5
        assert priya["occurrences"][-1]["updates"] == ["Pricing page shipped"]
        [repeat] = body["repeated_blockers"]
        assert repeat["person"] == "Priya Sharma" and repeat["times"] == 4
        # A colleague who can't read the series gets a 404, never the digest.
        denied = await client.get(f"/api/meetings/{current.id}/series/standup", headers=auth_headers(other_member_user))
        assert denied.status_code == 404
    finally:
        async with async_session() as db:
            from sqlalchemy import delete

            await db.execute(delete(Meeting).where(Meeting.series_key == series))
            await db.commit()


async def test_digest_only_uses_occurrences_the_reader_can_open(client, member_user, other_member_user):
    series = f"meet:{TEST_PREFIX}{uuid.uuid4().hex[:8]}"
    private = await _occurrence(member_user, series, 2, _sections(blockers=[("Priya", "Secret blocker")]))
    shared = await _occurrence(member_user, series, 0, _sections(updates=[("Priya", "Visible update")]))
    async with async_session() as db:
        db.add(MeetingAttendee(meeting_id=shared.id, user_id=other_member_user.id, display_name="O", access="granted"))
        await db.commit()
    try:
        body = (await client.get(f"/api/meetings/{shared.id}/series/standup", headers=auth_headers(other_member_user))).json()
        assert [o["id"] for o in body["occurrences"]] == [str(shared.id)]
        assert "Secret blocker" not in str(body)
    finally:
        async with async_session() as db:
            from sqlalchemy import delete

            await db.execute(delete(Meeting).where(Meeting.id.in_([private.id, shared.id])))
            await db.commit()


async def test_non_standup_series_returns_nothing(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "Plain one-off", None)
    body = (await client.get(f"/api/meetings/{meeting.id}/series/standup", headers=auth_headers(member_user))).json()
    assert body == {"occurrences": [], "people": [], "repeated_blockers": []}


def test_a_standup_with_plans_but_no_tasks_gets_its_commitments_as_tasks():
    from app.services import ai_extractor as ax

    evidence = [ax.EvidenceRef(segment=4, excerpt="I'll send the build tomorrow")]
    plans = ax.TemplateSection(heading="Plans", items=[
        ax.TemplateItem(text="Send a revised APK build by tomorrow morning", person="Prakhal", evidence=evidence),
        ax.TemplateItem(text="Someone should look at the bug sheet", person=""),  # nobody stated it: not a task
    ])
    blockers = ax.TemplateSection(heading="Blockers", items=[ax.TemplateItem(text="No TestFlight access", person="Prakhal")])
    parsed = ax.MeetingExtraction(template_sections=[blockers, plans])
    ax._plans_as_tasks(parsed, "standup")
    assert [(t.task, t.assignedTo, t.evidence) for t in parsed.tasks] == [
        ("Send a revised APK build by tomorrow morning", "Prakhal", evidence)
    ]
    # Tasks the model did extract are kept as they are; other templates are untouched.
    ax._plans_as_tasks(parsed, "standup")
    assert len(parsed.tasks) == 1
    general = ax.MeetingExtraction(template_sections=[plans])
    ax._plans_as_tasks(general, "general")
    assert general.tasks == []
