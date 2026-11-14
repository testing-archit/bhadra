"""People's names in Latin script.

Deepgram writes a name said in a Hindi sentence in Devanagari ("सार्थक"), and
the extractor sometimes copies it into a task owner or a stand-up person. That
breaks owner matching and shows Hindi in an English product. `latin_name`
transliterates it and, when the result sounds like exactly one known person,
returns that person's spelling ("Sarthak").
"""

import re
import unicodedata

from app.services.vocabulary_service import sound_key

DEVANAGARI = re.compile(r"[ऀ-ॿ]")

_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
}
_SIGNS = {
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
}
_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j",
    "झ": "jh", "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t",
    "थ": "th", "द": "d", "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh",
    "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s",
    "ह": "h", "ड़": "r", "ढ़": "rh", "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "फ़": "f",
}
_VIRAMA, _NUKTA = "्", "़"
_NASAL = {"ं": "n", "ँ": "n", "ः": "h"}


def _word(word: str) -> str:
    chars = list(unicodedata.normalize("NFD", word))
    out: list[str] = []
    i = 0
    while i < len(chars):
        char = chars[i]
        if i + 1 < len(chars) and chars[i + 1] == _NUKTA:
            char, i = char + _NUKTA, i + 1
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        if char in _CONSONANTS:
            out.append(_CONSONANTS[char])
            # The inherent "a", dropped before a vowel sign, a virama, or at the end.
            if nxt and nxt not in _SIGNS and nxt != _VIRAMA and nxt not in _NASAL:
                out.append("a")
        elif char in _SIGNS:
            out.append(_SIGNS[char])
        elif char in _VOWELS:
            out.append(_VOWELS[char])
        elif char in _NASAL:
            out.append(_NASAL[char])
        elif char != _VIRAMA:
            out.append(char)
        i += 1
    return "".join(out)


def transliterate(text: str) -> str:
    return " ".join(_word(w).capitalize() if DEVANAGARI.search(w) else w for w in text.split())


def latin_name(name: str | None, people: list[str]) -> str | None:
    """`name` unchanged unless it has Devanagari; then the one known person
    (or that person's word, for a single-word name) it sounds like, else a
    plain transliteration."""
    if not name or not DEVANAGARI.search(name):
        return name
    rough = transliterate(name)
    key = " ".join(sound_key(w) for w in rough.split())
    matches = set()
    for person in people:
        words = person.split()
        if " ".join(sound_key(w) for w in words) == key:
            matches.add(person)
        elif len(rough.split()) == 1:
            matches.update(w for w in words if sound_key(w) == key)
    return matches.pop() if len(matches) == 1 else rough
