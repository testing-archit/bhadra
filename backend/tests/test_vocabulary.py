import uuid
from unittest.mock import patch

from sqlalchemy import func

from app.database.db import async_session
from app.database.models import (
    KnownPerson,
    Meeting,
    MeetingAttendee,
    MeetingInsight,
    MeetingTask,
    TermCorrection,
    TermSuggestion,
    TranscriptSegment,
)
from app.services import vocabulary_service as vocab
from tests.conftest import auth_headers

PEOPLE = {"archit gupta", "archit", "gupta", "satyendra"}


def test_a_fixed_mishearing_is_detected():
    assert vocab.detect("Inquire with Ras about backend repository access", "Inquire with Raj about backend repository access") == [("Ras", "Raj")]
    assert vocab.detect("Demo the Sky Tech dashboard.", "Demo the Sky Lattice dashboard.") == [("Sky Tech", "Sky Lattice")]
    assert vocab.detect("Ask Satendra.", "Ask Satyendra.", PEOPLE) == [("Satendra", "Satyendra")]


def test_reassignments_rewrites_and_ordinary_edits_are_not_corrections():
    # Archit is a real person: this hands the task over, it isn't a mishearing.
    assert vocab.detect("Archit to test the build", "Satyendra to test the build", PEOPLE) == []
    # Rescheduling, unrelated words, lower-case wording changes.
    assert vocab.detect("Ship it on Monday", "Ship it on Friday") == []
    assert vocab.detect("Call Ravi about pricing", "Call Meera about pricing") == []
    assert vocab.detect("Check the build", "Check the release") == []
    # A rewritten sentence is not a set of corrections.
    assert vocab.detect("Ras will send the repo link today", "Raj sends repo access link tomorrow morning instead") == []
    assert vocab.detect("same text", "same text") == []


def test_apply_replaces_whole_words_in_any_capitalisation():
    text, counts = vocab.apply_text("Ras said ras's repo; Rasmus and RAS. sky  tech", [("Ras", "Raj"), ("Sky Tech", "Sky Lattice")])
    assert text == "Raj said Raj's repo; Rasmus and Raj. Sky Lattice"
    assert counts == {"Ras": 3, "Sky Tech": 1}


def test_apply_deep_leaves_ids_and_timings_alone():
    value = [{"title": "Ras repo", "evidence": [{"segment_id": "Ras", "excerpt": "ask Ras", "seq": 3}]}]
    fixed, counts = vocab.apply_deep(value, [("Ras", "Raj")])
    assert fixed == [{"title": "Raj repo", "evidence": [{"segment_id": "Ras", "excerpt": "ask Raj", "seq": 3}]}]
    assert sum(counts.values()) == 2
    assert value[0]["title"] == "Ras repo"  # a new object, not mutated


def test_new_transcripts_get_learned_fixes_and_keyterms():
    turns = [
        {"text": "Talk to Ras about Sky Tech", "words": [[0, 1]] * 6},
        {"text": "Nothing to fix", "words": [[0, 1]] * 3},
    ]
    vocabulary = vocab.Vocabulary(rules=[("Sky Tech", "Skylattice"), ("Ras", "Raj")], keywords=["Fixera"])
    applied = vocab.apply_to_turns(turns, vocabulary.rules)
    assert turns[0]["text"] == "Talk to Raj about Skylattice"
    assert "words" not in turns[0]  # 6 timings no longer match 5 words
    assert turns[1]["words"] == [[0, 1]] * 3
    assert applied == {"Sky Tech": 1, "Ras": 1}
    assert vocab.keyterms(["Archit"], vocabulary) == ["Archit", "Fixera", "Skylattice", "Raj"]


async def test_editing_a_task_fixes_the_meeting_and_learns(client, member_user, make_meeting):
    headers = auth_headers(member_user)
    meeting = await make_meeting(member_user, "Ras sync", "Engineering")
    wrong = f"Rasq{uuid.uuid4().hex[:4]}"
    right = "Raj" + wrong[4:]
    async with async_session() as db:
        db.add(TranscriptSegment(meeting_id=meeting.id, seq=0, speaker_key="0", text=f"Ask {wrong} for the repo.", original_text=f"Ask {wrong} for the repo."))
        db.add(MeetingInsight(meeting_id=meeting.id, next_steps=[f"Reach out to {wrong}"]))
        first = MeetingTask(meeting_id=meeting.id, description=f"Inquire with {wrong} about repo access")
        second = MeetingTask(meeting_id=meeting.id, description=f"Contact {wrong} regarding the repo")
        db.add_all([first, second])
        await db.commit()
        first_id, second_id = first.id, second.id

    try:
        response = await client.patch(
            f"/api/tasks/{first_id}", headers=headers, json={"description": f"Inquire with {right} about repo access"}
        )
        assert response.status_code == 200
        assert response.json()["learned_corrections"] == [{"wrong": wrong, "right": right}]

        async with async_session() as db:
            assert (await db.get(MeetingTask, second_id)).description == f"Contact {right} regarding the repo"
            assert (await db.get(MeetingInsight, meeting.id)).next_steps == [f"Reach out to {right}"]
            segments = (await db.execute(TranscriptSegment.__table__.select().where(TranscriptSegment.meeting_id == meeting.id))).all()
            assert segments[0].text == f"Ask {right} for the repo."
            learned = (await db.execute(TermCorrection.__table__.select().where(TermCorrection.wrong == wrong))).one()
            assert learned.right == right and learned.source == "learned"
    finally:
        async with async_session() as db:
            await db.execute(TermCorrection.__table__.delete().where(TermCorrection.wrong == wrong))
            await db.commit()


async def test_vocabulary_page_adds_keywords_and_rules(client, member_user):
    headers = auth_headers(member_user)
    term = f"Skylattice{uuid.uuid4().hex[:4]}"
    created = await client.post(
        "/api/vocabulary", headers=headers, json={"term": term, "heard_as": ["Sky Tech" + term[-4:], term], "fix_past": False}
    )
    assert created.status_code == 201
    entries = created.json()
    assert [(e["heard_as"], e["term"], e["source"]) for e in entries] == [("Sky Tech" + term[-4:], term, "manual")]
    keyword = (await client.post("/api/vocabulary", headers=headers, json={"term": term + "Kw"})).json()[0]
    assert keyword["kind"] == "keyword"

    try:
        switched = await client.patch(f"/api/vocabulary/{entries[0]['id']}", headers=headers, json={"enabled": False})
        assert switched.json()["enabled"] is False
        listed = await client.get("/api/vocabulary", headers=headers)
        assert {e["id"] for e in listed.json()} >= {entries[0]["id"], keyword["id"]}
    finally:
        for entry_id in (entries[0]["id"], keyword["id"]):
            assert (await client.delete(f"/api/vocabulary/{entry_id}", headers=headers)).status_code == 200


# --- applying is idempotent ---------------------------------------------------


def test_applying_a_rule_twice_never_doubles_it():
    rules = [("Lattice", "Sky Lattice")]
    once, counts = vocab.apply_text("Lattice and Sky Lattice", rules)
    assert once == "Sky Lattice and Sky Lattice" and counts == {"Lattice": 1}
    twice, counts = vocab.apply_text(once, rules)
    assert twice == once and not counts


# --- names reach the transcriber and the notes ---------------------------------


def test_the_meetings_people_are_listened_for_first():
    vocabulary = vocab.Vocabulary(
        rules=[("Ras", "Raj")], keywords=["Fixera"], people=["Archit Gupta", "Meera Iyer"], auto_keywords=["Acme"],
    )
    terms = vocab.keyterms(["Archit"], vocabulary, ["Priya Raman", "archit gupta", "priya@client.com"])
    assert terms == ["Priya Raman", "archit gupta", "Archit", "Fixera", "Raj", "Meera Iyer", "Acme"]
    many = vocab.Vocabulary(people=[f"Person {i}" for i in range(80)], auto_keywords=["Acme"])
    assert len(vocab.keyterms([], many, ["Guest"])) == vocab.MAX_KEYTERMS
    assert vocab.keyterms([], many, ["Guest"])[0] == "Guest"


def test_the_notes_model_is_told_how_names_are_spelled():
    vocabulary = vocab.Vocabulary(rules=[("Sky Tech", "Sky Lattice")], keywords=["Fixera"], people=["Archit Gupta", "Meera Iyer"])
    hint = vocab.prompt_hint(["Archit Gupta", "Priya Raman"], vocabulary)
    assert "People in this meeting: Archit Gupta, Priya Raman" in hint
    assert "Other people at the company and regular guests: Meera Iyer" in hint
    assert "Fixera" in hint and '"Sky Tech" means "Sky Lattice"' in hint
    assert vocab.prompt_hint([], vocab.Vocabulary()) == ""


def test_notes_never_bring_a_fixed_mishearing_back():
    extraction = {
        "summary": "Ras demoed Sky Tech.",
        "tasks": [{"task": "Ras to ship", "assignedTo": "Ras", "evidence": [{"segment": 2, "excerpt": "Ras will ship"}]}],
        "input_tokens": 10,
    }
    cleaned = vocab.clean_extraction(extraction, [("Ras", "Raj"), ("Sky Tech", "Sky Lattice")])
    assert cleaned["summary"] == "Raj demoed Sky Lattice."
    assert cleaned["tasks"][0]["assignedTo"] == "Raj" and cleaned["tasks"][0]["evidence"][0]["segment"] == 2
    assert cleaned["input_tokens"] == 10
    assert vocab.clean_extraction(extraction, []) is extraction


def test_attendee_lists_give_names_not_emails():
    assert vocab.people_from_attendees(["Archit", "a@b.com", {"name": "Priya", "email": "p@c.com"}, {"email": "x@y.z"}, 3]) == ["Archit", "Priya"]


# --- suggestions --------------------------------------------------------------


def test_sound_key_treats_likely_mishearings_alike():
    assert vocab.sound_key("Archit") == vocab.sound_key("Arshit") == vocab.sound_key("Orchid")
    assert vocab.sound_key("Satendra") == vocab.sound_key("Satyendra")
    assert vocab.sound_key("Archit") != vocab.sound_key("Meera")


def test_a_word_sounding_like_an_invitee_is_suggested():
    lines = [
        ("Okay so Arshit will take the deck.", 1000, 4000),
        ("I spoke to Arshit yesterday about the Pricing doc.", 5000, 9000),
        ("pricing is fine. Meera agrees.", 9000, 12000),
    ]
    found = vocab.find_suggestions(lines, ["Archit Gupta", "Meera Iyer"])
    assert [(s.wrong, s.right, s.occurrences, s.captions) for s in found] == [("Arshit", "Archit", 2, False)]


def test_suggestions_skip_real_people_known_terms_and_ordinary_words():
    lines = [("We asked Arshit and Rohan. Then Monday came, and Sky Lattice shipped with Teams.", 0, 5000)]
    # Arshit is someone's real name; Rohan doesn't sound like anyone invited.
    assert vocab.find_suggestions(lines, ["Archit Gupta"], protected={"arshit"}) == []
    assert vocab.find_suggestions(lines, ["Archit Gupta"], known_terms={"arshit"}) == []
    # A word that also appears in lower case is an ordinary word.
    assert vocab.find_suggestions([("Ask Mira. mira means ocean.", None, None)], ["Meera"]) == []
    # Sounds like two invitees equally: no guess.
    assert vocab.find_suggestions([("Ask Ravit today.", None, None)], ["Rohit", "Ravi T"]) in ([], [vocab.Suggestion("Ravit", "Rohit", 1, False)])


def test_captions_back_up_a_suggestion():
    lines = [("Then Vaybav will review.", 10_000, 13_000)]
    captions = [{"speaker": "Archit", "text": "then Vaibhav will review", "start": 10.5, "end": 12.0}]
    found = vocab.find_suggestions(lines, ["Vaibhav Shah"], captions=captions)
    assert found and found[0].wrong == "Vaybav" and found[0].right == "Vaibhav" and found[0].captions
    far = [{"speaker": "Archit", "text": "Vaibhav", "start": 60.0, "end": 61.0}]
    assert not vocab.find_suggestions(lines, ["Vaibhav Shah"], captions=far)[0].captions


def test_recurring_title_words_become_keywords():
    titles = ["Acme weekly sync", "Acme pricing review", "Fixera demo", "Standup", "Weekly Standup", "fixera notes", "Q4 Planning"]
    assert vocab.title_keywords(titles) == ["Acme"]


# --- database -------------------------------------------------------------------


async def test_teammates_list_people_and_guests(client, member_user, make_meeting):
    headers = auth_headers(member_user)
    guest = f"Priya Raman {uuid.uuid4().hex[:4]}"
    meetings = [await make_meeting(member_user, f"Acme call {i}", "Engineering") for i in range(2)]
    async with async_session() as db:
        for meeting in meetings:
            db.add(MeetingAttendee(meeting_id=meeting.id, user_id=member_user.id, display_name=member_user.name, access="granted"))
            db.add(MeetingAttendee(meeting_id=meeting.id, user_id=None, display_name=guest, access="granted"))
        await db.commit()

    people = (await client.get("/api/vocabulary/people", headers=headers)).json()
    row = next(p for p in people if p["name"] == guest)
    assert row["kind"] == "guest" and row["meetings"] == 2

    added = await client.post("/api/vocabulary/people", headers=headers, json={"name": guest, "note": "Client at Acme"})
    assert added.status_code == 201
    person_id = added.json()["id"]
    try:
        rules = await client.post("/api/vocabulary", headers=headers, json={"term": guest, "heard_as": ["Pria Raman" + guest[-4:]], "fix_past": False})
        assert rules.status_code == 201
        people = (await client.get("/api/vocabulary/people", headers=headers)).json()
        row = next(p for p in people if p["name"] == guest)
        assert row["kind"] == "added" and row["note"] == "Client at Acme" and row["can_delete"]
        assert [r["heard_as"] for r in row["heard_as"]] == ["Pria Raman" + guest[-4:]]
        # Someone's real name can't be made a mishearing.
        refused = await client.post("/api/vocabulary", headers=headers, json={"term": "Somebody", "heard_as": [guest]})
        assert refused.status_code == 422
        await client.delete(f"/api/vocabulary/{rules.json()[0]['id']}", headers=headers)
    finally:
        assert (await client.delete(f"/api/vocabulary/people/{person_id}", headers=headers)).status_code == 200


async def test_a_meeting_suggests_a_correction_that_can_be_accepted(client, member_user, make_meeting):
    headers = auth_headers(member_user)
    suffix = uuid.uuid4().hex[:4]
    invitee, misheard = f"Vaibhav{suffix}", f"Vaybav{suffix}"
    meeting = await make_meeting(member_user, "Design sync", "Engineering", transcript=f"Speaker 1: Then {misheard} will review it.")
    async with async_session() as db:
        db.add(MeetingAttendee(meeting_id=meeting.id, user_id=member_user.id, display_name=member_user.name, access="granted"))
        db.add(MeetingAttendee(meeting_id=meeting.id, user_id=None, display_name=f"{invitee} Shah", access="granted"))
        db.add(TranscriptSegment(meeting_id=meeting.id, seq=0, speaker_key="0", text=f"Then {misheard} will review it.", original_text="x", start_ms=0, end_ms=3000))
        await db.commit()

    try:
        with patch.object(vocab, "refresh_auto_keywords"):
            await vocab.learn_from_meeting(meeting.id)
        listed = (await client.get("/api/vocabulary/suggestions", headers=headers)).json()
        suggestion = next(s for s in listed if s["heard_as"] == misheard)
        assert suggestion["term"] == invitee and suggestion["meeting_id"] == str(meeting.id)

        accepted = await client.post(f"/api/vocabulary/suggestions/{suggestion['id']}/accept", headers=headers, json={"fix_past": True})
        assert accepted.status_code == 200 and accepted.json()["source"] == "suggested"
        async with async_session() as db:
            segment = (await db.execute(TranscriptSegment.__table__.select().where(TranscriptSegment.meeting_id == meeting.id))).one()
            assert segment.text == f"Then {invitee} will review it."
        again = await client.post(f"/api/vocabulary/suggestions/{suggestion['id']}/dismiss", headers=headers)
        assert again.status_code == 409
    finally:
        async with async_session() as db:
            await db.execute(TermCorrection.__table__.delete().where(TermCorrection.wrong == misheard))
            await db.execute(TermSuggestion.__table__.delete().where(TermSuggestion.wrong == misheard))
            await db.commit()


async def test_heard_in_enough_meetings_a_suggestion_applies_itself(member_user, make_meeting):
    suffix = uuid.uuid4().hex[:4]
    invitee, misheard = f"Vaibhav{suffix}", f"Vaybav{suffix}"
    meetings = []
    for _ in range(3):
        meeting = await make_meeting(member_user, "Design sync", "Engineering")
        async with async_session() as db:
            db.add(MeetingAttendee(meeting_id=meeting.id, user_id=None, display_name=invitee, access="granted"))
            db.add(TranscriptSegment(meeting_id=meeting.id, seq=0, speaker_key="0", text=f"Ask {misheard} first.", original_text="x"))
            await db.commit()
        meetings.append(meeting)
    try:
        with patch.object(vocab, "refresh_auto_keywords"):
            for meeting in meetings:
                await vocab.learn_from_meeting(meeting.id)
        async with async_session() as db:
            rule = (await db.execute(TermCorrection.__table__.select().where(TermCorrection.wrong == misheard))).one()
            assert rule.right == invitee and rule.source == "suggested"
            texts = (await db.execute(
                TranscriptSegment.__table__.select().where(TranscriptSegment.meeting_id.in_([m.id for m in meetings]))
            )).all()
            assert {t.text for t in texts} == {f"Ask {invitee} first."}
    finally:
        async with async_session() as db:
            await db.execute(TermCorrection.__table__.delete().where(TermCorrection.wrong == misheard))
            await db.execute(TermSuggestion.__table__.delete().where(TermSuggestion.wrong == misheard))
            await db.commit()


async def test_regenerated_notes_use_the_vocabulary(client, member_user, make_meeting):
    headers = auth_headers(member_user)
    suffix = uuid.uuid4().hex[:4]
    wrong, right = f"Rasq{suffix}", f"Raj{suffix}"
    meeting = await make_meeting(member_user, "Repo sync", "Engineering")
    async with async_session() as db:
        db.add(TermCorrection(wrong=wrong, right=right, source="manual"))
        db.add(TranscriptSegment(meeting_id=meeting.id, seq=0, speaker_key="0", text=f"{wrong} will share the repo.", original_text="x"))
        await db.commit()
    extraction = {
        "title": "", "tasks": [{"task": f"{wrong} to share the repo", "assignedTo": wrong, "dueDate": "", "resolvedDueDate": "", "priority": "Medium",
                                "project": "", "evidence": [{"segment": 0, "excerpt": f"{wrong} will share"}]}],
        "decisions": [], "risks": [], "summary": f"{wrong} shares the repo.", "overview": "", "key_topics": [], "open_questions": [],
        "highlights": [], "next_steps": [], "sections": [], "template_sections": [], "follow_up_draft": "", "speaker_activity": [],
        "template": "general", "model": "test", "prompt_version": "test", "chunk_count": 1,
        "input_tokens": 0, "output_tokens": 0, "cache_tokens_read": 0, "cache_tokens_written": 0,
    }
    try:
        with patch("app.services.ai_extractor.extract_from_transcript", return_value=extraction) as mock:
            response = await client.post(f"/api/meetings/{meeting.id}/insights/regenerate", json={}, headers=headers)
        assert response.status_code == 200, response.text
        assert f"{right} will share the repo." in [s.text for s in mock.call_args.kwargs["segments"]]
        assert f'"{wrong}" means "{right}"' in mock.call_args.kwargs["vocabulary_hint"]
        async with async_session() as db:
            stored = await db.get(Meeting, meeting.id)
            assert stored.summary == f"{right} shares the repo."
            task = (await db.execute(MeetingTask.__table__.select().where(MeetingTask.meeting_id == meeting.id))).one()
            assert task.description == f"{right} to share the repo" and task.owner == right
    finally:
        async with async_session() as db:
            await db.execute(TermCorrection.__table__.delete().where(TermCorrection.wrong == wrong))
            await db.commit()
