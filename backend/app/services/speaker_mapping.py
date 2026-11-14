"""Turn the notetaker bot's two views of a meeting into one named transcript.

The bot captures the call twice: the raw audio, which Deepgram diarizes into
anonymous speakers ("Speaker 1", "Speaker 2"), and Google Meet's live
captions, which carry each speaker's real display name but mediocre text.
Lining the two up by time gives Deepgram-quality text with Meet's names —
which is why the bot records captions at all.
"""

import re
from collections import defaultdict

# Meet renders a caption a beat after the words are spoken, so a caption's
# window is stretched backwards by this much before overlaps are measured.
CAPTION_LAG_SECONDS = 1.5
# A diarized speaker is only named when one caption name accounts for at least
# this share of its caption overlap — otherwise it keeps its generic label
# rather than borrowing a name that is only partly right.
MIN_NAME_SHARE = 0.5
MIN_OVERLAP_SECONDS = 2.0
# Deepgram sometimes splits one voice into a main speaker plus a small
# fragment, which rightly share a name. Two voices that each talked a lot are
# two people, though: when Meet only captioned one of them (someone's captions
# went missing), the other used to inherit the same name and the whole call
# read as one person. A voice beyond the name's best match keeps the name only
# while it talked at most this fraction as long as that match.
MAX_FRAGMENT_RATIO = 0.35
# A real fragment sits under that name's captions about as much as its main
# voice does. A voice that only inherited the name because nothing else fit
# (its own words went uncaptioned — Meet often drops Hindi speech) sits under
# them far less, and is someone else (production, 2026-10-13: Sarthak and
# Anmol each spoke a minute but were captioned 3 and 5 times, and both became
# "Ravi"). Such a voice takes a caption name nobody claimed when it overlaps
# that name's captions, else keeps its generic label.
MIN_FRAGMENT_SUPPORT = 0.5


# While someone shares their screen, Meet credits what they say to the
# presentation tile ("Archit Gupta's Presentation"), which otherwise becomes a
# separate "person" in the transcript and the attendee list.
_PRESENTATION_NAME = re.compile(
    r"^\s*(?:(?P<a>.+?)['’]s\s+presentation|presentation\s*\((?P<b>.+?)\)|(?P<c>.+?)\s*\(presenting\))\s*$",
    re.IGNORECASE,
)


def speaker_display_name(name: str | None) -> str:
    """A caption speaker's person: "X's Presentation" is X."""
    name = (name or "").strip()
    match = _PRESENTATION_NAME.match(name)
    if match:
        return next(group for group in match.groups() if group).strip()
    return name


# Meet keeps a speaker's caption block open (and keeps revising its text)
# long after the words were said, so blocks often span 30-140 s and several
# people's blocks overlap. Time overlap alone then splits every voice across
# names and nobody gets named. The words themselves are the stronger signal:
# a turn is matched to the captions near it that say the same words.
WORD_WINDOW_SECONDS = 5.0
# Fewer shared words than this is no evidence; the time overlap decides.
MIN_WORD_EVIDENCE = 4
_LATIN_WORD = re.compile(r"[a-z]{3,}")


def _words(text: str) -> set[str]:
    # Latin script only: Deepgram writes Hindi in Devanagari while Meet's
    # captions romanise it, so only English and romanised words can match.
    return set(_LATIN_WORD.findall((text or "").lower()))


def _majority(scores: dict[str, float], minimum: float) -> str | None:
    """The name holding at least MIN_NAME_SHARE of the evidence (and at least
    `minimum` of it), if any."""
    total = sum(scores.values())
    if not total:
        return None
    name, score = max(scores.items(), key=lambda item: item[1])
    return name if score >= minimum and score / total >= MIN_NAME_SHARE else None


def name_speakers(
    turns: list[dict], captions: list[dict], exclude_names: set[str] | None = None
) -> dict[str, str]:
    """Map Deepgram speaker ids (as strings, the speaker_names.json format) to
    caption display names: by the words a speaker's turns share with nearby
    captions, else by how long they overlap in time."""
    excluded = {name.strip().lower() for name in exclude_names or set()}
    usable = [
        c
        for c in captions
        if (c.get("speaker") or "").strip()
        and c["speaker"].strip().lower() not in excluded
        and float(c.get("end", 0)) > float(c.get("start", 0))
    ]
    if not usable:
        return {}
    caption_words = [_words(c.get("text") or "") for c in usable]

    overlap: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    matched: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    talk: dict[int, float] = defaultdict(float)
    for turn in turns:
        speaker = int(turn["speaker"])
        turn_start, turn_end = float(turn["start"]), float(turn["end"])
        talk[speaker] += max(turn_end - turn_start, 0.0)
        turn_words = _words(turn.get("text") or "")
        for caption, words in zip(usable, caption_words):
            name = caption["speaker"].strip()
            start = float(caption["start"]) - CAPTION_LAG_SECONDS
            end = float(caption["end"])
            shared = min(turn_end, end) - max(turn_start, start)
            if shared > 0:
                overlap[speaker][name] += shared
            if turn_words and start - WORD_WINDOW_SECONDS <= turn_end and end + WORD_WINDOW_SECONDS >= turn_start:
                matched[speaker][name] += len(turn_words & words)

    # Louder voices choose first. A quieter voice whose best name is already
    # taken (or contested) prefers the best name nobody bigger has claimed:
    # with three or more people, a long-winded speaker's captions blanket
    # everyone else's words, and the quiet person in the call would otherwise
    # be filed as a "fragment" of them while their own caption name goes
    # unused (production, 2026-10-12: Anmol's turns credited to Ravi).
    claims: dict[str, list[int]] = defaultdict(list)
    for speaker in sorted(set(overlap) | set(matched), key=lambda s: -talk[s]):
        by_words = matched.get(speaker) or {}
        if sum(by_words.values()) >= MIN_WORD_EVIDENCE:
            scores, minimum = by_words, MIN_WORD_EVIDENCE
        else:
            scores, minimum = overlap.get(speaker) or {}, MIN_OVERLAP_SECONDS
        name = _majority(scores, 0 if scores is by_words else minimum)
        if name is None or name in claims:
            free = _majority({n: s for n, s in scores.items() if n not in claims}, minimum)
            name = free or name
        if name is not None:
            claims[name].append(speaker)

    def support(speaker: int, name: str) -> float:
        # Share of this voice's talk that sits under the name's captions.
        return overlap[speaker].get(name, 0.0) / talk[speaker] if talk[speaker] else 0.0

    names: dict[str, str] = {}
    unplaced: list[int] = []
    for name, speakers in claims.items():
        best = max(speakers, key=lambda speaker: talk[speaker])
        names[str(best)] = name
        for speaker in speakers:
            if speaker == best:
                continue
            if talk[speaker] <= talk[best] * MAX_FRAGMENT_RATIO and support(speaker, name) >= support(best, name) * MIN_FRAGMENT_SUPPORT:
                names[str(speaker)] = name
            else:
                unplaced.append(speaker)

    # Names nobody claimed go to the unplaced voice whose talk their captions
    # cover most — strongest evidence first, one voice per name.
    unclaimed = {caption["speaker"].strip() for caption in usable} - set(claims)
    candidates = sorted(
        (
            (overlap[speaker].get(name, 0.0) + matched[speaker].get(name, 0.0), speaker, name)
            for speaker in unplaced
            for name in unclaimed
        ),
        reverse=True,
    )
    for evidence, speaker, name in candidates:
        if evidence < MIN_OVERLAP_SECONDS or str(speaker) in names or name not in unclaimed:
            continue
        names[str(speaker)] = name
        unclaimed.discard(name)
    return names


def captions_transcript(captions: list[dict], exclude_names: set[str] | None = None) -> str:
    """The fallback transcript when there is no usable audio: Meet's own
    captions, one "Name: text" line per caption block."""
    excluded = {name.strip().lower() for name in exclude_names or set()}
    lines = []
    for caption in sorted(captions, key=lambda c: float(c.get("start", 0))):
        speaker = (caption.get("speaker") or "").strip() or "Unknown speaker"
        text = (caption.get("text") or "").strip()
        if text and speaker.lower() not in excluded:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)
