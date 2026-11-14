"""Due-date phrases in English.

The extractor is told to write every task's spoken deadline ("aaj shaam tak")
in English, but a model sometimes copies Hindi words in Devanagari straight
from the transcript ("आज शाम तक"). `english_due_phrase` translates the common
deadline words and, when anything non-Latin is still left, falls back to the
resolved calendar date — never shows Hindi script to a reader.
"""

import re
import unicodedata
from datetime import date

_NON_LATIN = re.compile(r"[^\x00-ɏ -⁯₹]")

_NUMBERS = {
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "छः": 6, "सात": 7,
    "आठ": 8, "नौ": 9, "दस": 10, "ग्यारह": 11, "बारह": 12,
}
# Spoken times: "साढ़े चार बजे" 4:30, "सवा दो" 2:15, "पौने तीन" 2:45, "डेढ़" 1:30, "ढाई" 2:30.
_TIME = re.compile(r"(?:(साढ़े|साढे|सवा|पौने)\s+)?(?!डेढ|ढाई)(\S+)\s+बजे|(डेढ़|डेढ|ढाई)\s+बजे")

_WORDS = [
    ("परसों", "the day after tomorrow"), ("आज", "today"), ("कल", "tomorrow"),
    ("सुबह", "morning"), ("दोपहर", "afternoon"), ("शाम", "evening"), ("रात", "night"),
    ("सोमवार", "Monday"), ("मंगलवार", "Tuesday"), ("बुधवार", "Wednesday"), ("गुरुवार", "Thursday"),
    ("बृहस्पतिवार", "Thursday"), ("शुक्रवार", "Friday"), ("शनिवार", "Saturday"), ("रविवार", "Sunday"),
    ("अगले", "next"), ("अगला", "next"), ("इस", "this"), ("हफ़्ते", "week"), ("हफ्ते", "week"),
    ("हफ़्ता", "week"), ("हफ्ता", "week"), ("महीने", "month"), ("महीना", "month"),
    ("के अंत", "end of the"), ("अंत", "end"), ("से पहले", "before"), ("के बाद", "after"),
    ("तक", "by"), ("को", ""), ("में", "in"), ("के", ""), ("की", ""), ("का", ""),
]


def _nfc(text: str) -> str:
    # "ढ़" arrives both precomposed and as ढ + nukta; NFC makes them one.
    return unicodedata.normalize("NFC", text)


_NUMBERS = {_nfc(k): v for k, v in _NUMBERS.items()}
_TIME = re.compile(_nfc(_TIME.pattern))
_WORDS = [(_nfc(hindi), english) for hindi, english in _WORDS]


def _time(match: re.Match) -> str:
    if match.group(3):
        return "1:30" if match.group(3).startswith("ड") else "2:30"
    hour = _NUMBERS.get(match.group(2))
    if hour is None:
        return match.group(0)
    modifier = match.group(1)
    if modifier in (_nfc("साढ़े"), "साढे"):
        return f"{hour}:30"
    if modifier == "सवा":
        return f"{hour}:15"
    if modifier == "पौने":
        return f"{hour - 1 or 12}:45"
    return f"{hour} o'clock"


def _translate(phrase: str) -> str:
    text = _TIME.sub(_time, _nfc(phrase))
    for hindi, english in _WORDS:
        text = re.sub(rf"(?<!\S){re.escape(hindi)}(?!\S)", english, text)
    words = text.split()
    # Hindi puts "तक" (by) last: "आज शाम by" → "by this evening".
    if words and words[-1] == "by":
        words = ["by"] + words[:-1]
    text = " ".join(words)
    text = re.sub(r"\btoday evening\b", "this evening", text)
    text = re.sub(r"\btoday morning\b", "this morning", text)
    text = re.sub(r"\btoday night\b", "tonight", text)
    return text.strip()


def english_due_phrase(phrase: str | None, resolved: date | None = None) -> str | None:
    """`phrase` with any Hindi script translated; the resolved date (or None)
    when it can't be."""
    if not phrase or not _NON_LATIN.search(phrase):
        return phrase
    translated = _translate(phrase)
    if translated and not _NON_LATIN.search(translated):
        return translated
    return resolved.strftime("%a %-d %b") if resolved else None
