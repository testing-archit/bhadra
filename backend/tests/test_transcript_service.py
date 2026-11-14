"""Pure tests for transcript parsing, evidence validation, citations and the
extraction post-processing rules — no database, no network."""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.config import settings
from app.database.models import TranscriptSegment
from app.services import ai_extractor, capture_service, insight_service, memory_retriever, transcript_service


def _seg(seq: int, text: str, speaker: str = "0", start: int | None = None, end: int | None = None) -> TranscriptSegment:
    return TranscriptSegment(
        id=uuid.uuid4(), seq=seq, speaker_key=speaker, speaker_label=None,
        text=text, original_text=text, start_ms=start, end_ms=end,
    )


# --- parsing -------------------------------------------------------------------


def test_plain_text_gets_no_invented_timestamps_or_speakers():
    segments = transcript_service.parse_transcript_text("We should ship on Friday.\nAnd tell the client.")
    assert len(segments) == 1  # continuation lines join the same unattributed turn
    assert segments[0]["start_ms"] is None and segments[0]["end_ms"] is None
    assert segments[0]["speaker_key"] == "" and segments[0]["speaker_label"] is None
    assert segments[0]["confidence"] is None


def test_named_and_generic_speakers():
    segments = transcript_service.parse_transcript_text("Priya: Budget is 5 lakh.\nSpeaker 2: Not 50 lakh.")
    assert segments[0]["speaker_label"] == "Priya"
    # "Speaker 2" is the diarizer's generic label: key "1", no stated name.
    assert segments[1]["speaker_key"] == "1" and segments[1]["speaker_label"] is None
    assert segments[1]["text"] == "Not 50 lakh."


def test_prose_colons_are_not_speakers():
    segments = transcript_service.parse_transcript_text("Note: the server is down at 10:30 today")
    assert segments[0]["speaker_label"] is None
    assert segments[0]["text"].startswith("Note:")


def test_leading_timestamps_are_preserved_and_end_times_come_only_from_the_next_line():
    segments = transcript_service.parse_transcript_text("[00:01:05] Asha: hello\n[00:01:09] Ravi: hi")
    assert segments[0]["start_ms"] == 65_000 and segments[0]["end_ms"] == 69_000
    assert segments[1]["start_ms"] == 69_000 and segments[1]["end_ms"] is None


def test_webvtt_with_voice_tags():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:04.500\n<v Asha>We will not launch Monday.</v>\n\n00:00:05.000 --> 00:00:07.000\n<v Ravi>Agreed."
    segments = transcript_service.parse_transcript_text(vtt)
    assert [s["speaker_label"] for s in segments] == ["Asha", "Ravi"]
    assert segments[0]["start_ms"] == 1000 and segments[0]["end_ms"] == 4500
    assert segments[0]["text"] == "We will not launch Monday."


def test_srt():
    srt = "1\n00:00:01,000 --> 00:00:02,000\nAsha: one\n\n2\n00:00:03,000 --> 00:00:04,250\nRavi: two\n"
    segments = transcript_service.parse_transcript_text(srt)
    assert [(s["speaker_label"], s["end_ms"]) for s in segments] == [("Asha", 2000), ("Ravi", 4250)]


def test_json_segments():
    segments = transcript_service.parse_transcript_text('[{"speaker": "Asha", "text": "hi", "start": 1.5, "end": 2}]')
    assert segments == [{"speaker_key": "Asha", "speaker_label": "Asha", "text": "hi", "start_ms": 1500, "end_ms": 2000, "confidence": None}]


# --- exports & analytics -------------------------------------------------------


def _meeting():
    import datetime

    return SimpleNamespace(id=uuid.uuid4(), title="Launch", date=datetime.datetime(2026, 10, 6, tzinfo=datetime.UTC), transcript_revision=2)


def test_subtitle_exports_require_real_timestamps():
    untimed = [_seg(0, "hello")]
    with pytest.raises(transcript_service.ExportUnavailable):
        transcript_service.export(_meeting(), untimed, "srt")
    content, _, ext = transcript_service.export(_meeting(), untimed, "txt")
    assert ext == "txt" and "Speaker 1: hello" in content

    timed = [_seg(0, "hello", start=1000, end=2500), _seg(1, "bye", "1", 3000, 3600)]
    srt, _, _ = transcript_service.export(_meeting(), timed, "srt")
    assert "00:00:01,000 --> 00:00:02,500" in srt
    vtt, _, _ = transcript_service.export(_meeting(), timed, "vtt")
    assert vtt.startswith("WEBVTT") and "<v Speaker 2>bye" in vtt


def test_talk_time_counts_overlap_for_both_speakers():
    segments = [_seg(0, "a b c", "0", 0, 10_000), _seg(1, "d", "1", 5_000, 10_000)]
    result = transcript_service.talk_time(segments)
    by_key = {row["speaker_key"]: row for row in result["speakers"]}
    assert by_key["0"]["seconds"] == 10.0 and by_key["1"]["seconds"] == 5.0
    assert result["total_speaking_seconds"] == 15.0  # exceeds the 10s span: overlap is double counted
    assert result["transcript_span_seconds"] == 10.0


def test_talk_time_without_timestamps_uses_words():
    result = transcript_service.talk_time([_seg(0, "one two three"), _seg(1, "four", "1")])
    assert result["timed"] is False and result["basis"] == "words"
    assert result["speakers"][0]["seconds"] is None


# --- evidence ------------------------------------------------------------------


def test_evidence_validation():
    segments = {s.seq: s for s in [_seg(0, "Hello all"), _seg(1, "Ravi will send the deck by Friday", start=4000), _seg(2, "ok")]}
    refs, flags, rejected = insight_service.validate_evidence(
        [{"segment": 1, "excerpt": "Ravi will send the deck"}, {"segment": 99, "excerpt": "x"}], segments
    )
    assert rejected == 1 and flags == []
    assert refs[0]["verified"] is True and refs[0]["start_ms"] == 4000

    # Off by one: the quote is really in the neighbouring line.
    refs, flags, _ = insight_service.validate_evidence([{"segment": 2, "excerpt": "send the deck"}], segments)
    assert refs[0]["seq"] == 1 and refs[0]["verified"] is True

    # A quote that appears nowhere is kept for review but marked unverified.
    refs, flags, _ = insight_service.validate_evidence([{"segment": 0, "excerpt": "we agreed on pricing"}], segments)
    assert refs[0]["verified"] is False and flags == ["evidence_unverified"]

    refs, flags, _ = insight_service.validate_evidence([], segments)
    assert refs == [] and flags == ["evidence_missing"]


# --- extraction post-processing --------------------------------------------------


def test_tentative_decisions_are_not_decisions_and_unknown_owners_stay_empty():
    parsed = ai_extractor.MeetingExtraction(
        tasks=[
            ai_extractor.ExtractedTask(task="Check the SIP AUM calculation", assignedTo="", dueDate="next Friday", resolvedDueDate="2026-10-16", dueDateAmbiguous=True),
        ],
        decisions=[
            ai_extractor.ExtractedDecision(decision="Use PostgreSQL", status="confirmed"),
            ai_extractor.ExtractedDecision(decision="Maybe move to Neon", status="tentative"),
        ],
    )
    usage = {"input_tokens": 1, "output_tokens": 1, "cache_tokens_read": 0, "cache_tokens_written": 0}
    with patch.object(settings, "gemini_api_key", "test"), patch("app.services.ai_extractor.generate_structured", return_value=(parsed, usage)):
        result = ai_extractor.extract_from_transcript("Speaker 1: hi", segments=[_seg(0, "hi")])
    assert [d["decision"] for d in result["decisions"]] == ["Use PostgreSQL"]
    assert "Proposed, not confirmed: Maybe move to Neon" in result["open_questions"]
    assert result["tasks"][0]["assignedTo"] == ""
    # An ambiguous deadline never becomes a calendar date.
    assert result["tasks"][0]["resolvedDueDate"] == ""
    assert result["prompt_version"] == ai_extractor.EXTRACTION_PROMPT_VERSION


def test_long_transcripts_are_chunked_and_synthesized():
    segments = [_seg(i, "word " * 40) for i in range(30)]
    part = ai_extractor.MeetingExtraction(summary="part", tasks=[ai_extractor.ExtractedTask(task="Same task")])
    synthesis = ai_extractor._Synthesis(summary="whole", overview="o", followUpSubject="s", followUpBody="b")
    usage = {"input_tokens": 1, "output_tokens": 1, "cache_tokens_read": 0, "cache_tokens_written": 0}
    calls = []

    def fake(system, prompt, schema, **kwargs):
        calls.append(schema)
        return (synthesis if schema is ai_extractor._Synthesis else part), usage

    with patch.object(settings, "gemini_api_key", "test"), patch.object(settings, "extraction_chunk_chars", 2000), patch("app.services.ai_extractor.generate_structured", side_effect=fake):
        result = ai_extractor.extract_from_transcript("x", segments=segments)
    assert result["chunk_count"] > 1
    assert calls[-1] is ai_extractor._Synthesis
    assert result["summary"] == "whole"
    assert len(result["tasks"]) == 1  # duplicates across chunk borders collapse
    assert result["input_tokens"] == len(calls)


def test_fixture_mode_is_labelled_and_refused_in_production():
    with patch.object(settings, "fixture_mode", True), patch.object(settings, "app_env", "production"):
        assert settings.fixture_mode_active is False
    with patch.object(settings, "fixture_mode", True), patch.object(settings, "app_env", "development"), patch.object(settings, "gemini_api_key", ""):
        result = ai_extractor.extract_from_transcript("hi", segments=[_seg(0, "hi")])
    assert "fixture" in result["summary"].lower() and result["model"] == "development-fixture"


# --- grounded chat ----------------------------------------------------------------


def test_invented_citations_are_stripped():
    meeting = {
        "id": "m1", "title": "Pricing", "date": "2026-10-01",
        "segments": [{"id": "s0", "seq": 0, "start_ms": 0, "speaker": "Asha", "text": "Price stays at 5 lakh"}],
        "decisions": [], "tasks": [],
    }
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_tokens_read": 0, "cache_tokens_written": 0}
    with patch("app.services.memory_retriever.generate_text", return_value=("Price is 5 lakh [M1:S0], also [M1:S7] and [M3].", usage)) as generate:
        result = memory_retriever.answer_query_for_meetings("price?", [meeting])
    assert result["answer"] == "Price is 5 lakh [M1:S0], also  and ."
    assert result["sources"][0]["segments"][0]["segment_id"] == "s0"
    assert "untrusted data" in generate.call_args.args[0]


# --- capture URLs --------------------------------------------------------------------


def test_meeting_url_normalization():
    assert capture_service.normalize_meeting_url("meet.google.com/ABC-defg-hij?authuser=1") == (
        "google_meet", "abc-defg-hij", "https://meet.google.com/abc-defg-hij"
    )
    with pytest.raises(capture_service.InvalidMeetingUrl, match="Zoom"):
        capture_service.normalize_meeting_url("https://us02web.zoom.us/j/123")
    with pytest.raises(capture_service.InvalidMeetingUrl):
        capture_service.normalize_meeting_url("https://meet.google.com.evil.example/abc-defg-hij")


def test_teams_links_keep_what_joining_needs_and_stay_on_teams():
    platform, code, url = capture_service.normalize_meeting_url("https://teams.microsoft.com/meet/29384756102345?p=AbC123&x=1")
    assert (platform, code) == ("microsoft_teams", "teams-29384756102345")
    assert url == "https://teams.microsoft.com/meet/29384756102345?p=AbC123"
    assert "AbC123" not in code
    assert capture_service.normalize_meeting_url("teams.live.com/meet/9384756102345")[2] == "https://teams.live.com/meet/9384756102345"

    join = (
        "https://teams.microsoft.com/l/meetup-join/19%3ameeting_ZmFrZQ%40thread.v2/0"
        "?context=%7b%22Tid%22%3a%22abc%22%7d"
    )
    _, join_code, join_url = capture_service.normalize_meeting_url(join)
    assert join_code.startswith("teams-") and "%" not in join_code
    assert join_url == (
        "https://teams.microsoft.com/l/meetup-join/19%3Ameeting_ZmFrZQ%40thread.v2/0"
        "?context=%7B%22Tid%22%3A%22abc%22%7D"
    )


def test_teams_link_wrappers_lead_to_the_same_meeting():
    direct = capture_service.normalize_meeting_url("https://teams.microsoft.com/meet/29384756102345?p=AbC123")
    for wrapped in (
        "https://teams.microsoft.com/dl/launcher/launcher.html?url=%2F_%23%2Fmeet%2F29384756102345%3Fp%3DAbC123%26anon%3Dtrue&type=meet",
        "https://teams.microsoft.com/v2/?meetingjoin=true#/meet/29384756102345?p=AbC123",
        "https://teams.microsoft.com/meet/29384756102345?p=AbC123#stray",
        "https://nam02.safelinks.protection.outlook.com/?url=https%3A%2F%2Fteams.microsoft.com%2Fmeet%2F29384756102345%3Fp%3DAbC123&data=x",
    ):
        assert capture_service.normalize_meeting_url(wrapped) == direct, wrapped


@pytest.mark.parametrize(
    "link",
    [
        "https://teams.microsoft.com.evil.example/meet/29384756102345?p=x",
        "https://teams.microsoft.com@evil.example/meet/29384756102345?p=x",
        "https://evil.example/?u=teams.microsoft.com/meet/29384756102345",
        "javascript://teams.microsoft.com/meet/29384756102345",
        "https://nam02.safelinks.protection.outlook.com/?url=https%3A%2F%2Fevil.example%2Fmeet%2F29384756102345",
        "https://teams.microsoft.com/",
        "https://teams.microsoft.com/meet/abc",
        "https://teams.microsoft.com/l/meetup-join/not-a-thread/0",
    ],
)
def test_links_that_only_look_like_teams_are_refused(link):
    with pytest.raises(capture_service.InvalidMeetingUrl):
        capture_service.normalize_meeting_url(link)


def test_capture_transitions_never_go_backwards():
    assert capture_service.can_transition("requested", "joining")
    assert capture_service.can_transition("capturing", "denied") is True
    assert capture_service.can_transition("capturing", "joining") is False
    assert capture_service.can_transition("denied", "capturing") is False
    assert capture_service.can_transition("stopped", "completed") is True
    assert capture_service.can_transition("completed", "failed") is False


def test_word_times_kept_only_when_they_line_up_with_the_text():
    from app.services.transcript_service import segments_from_turns

    turns = [
        {"speaker": 0, "start": 1.0, "end": 2.2, "text": "Ship it today.", "words": [[1000, 1300], [1350, 1600], [1650, 2200]]},
        {"speaker": 1, "start": 3.0, "end": 4.0, "text": "Okay then", "words": [[3000, 3500]]},  # mismatch
        {"speaker": 1, "start": 5.0, "end": 6.0, "text": "Older turn"},  # before word times were kept
    ]
    first, second, third = segments_from_turns(turns)
    assert first["word_times"] == [[1000, 1300], [1350, 1600], [1650, 2200]]
    assert second["word_times"] is None and third["word_times"] is None


def test_build_turns_records_each_words_time():
    from app.services.transcriber import _build_turns

    words = [
        {"word": "ship", "punctuated_word": "Ship", "start": 1.0, "end": 1.3, "speaker": 0, "confidence": 0.9},
        {"word": "it", "punctuated_word": "it.", "start": 1.35, "end": 1.6, "speaker": 0, "confidence": 0.9},
    ]
    [turn] = _build_turns(words)
    assert turn["text"] == "Ship it." and turn["words"] == [[1000, 1300], [1350, 1600]]
