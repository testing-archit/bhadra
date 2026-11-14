from datetime import date

from app.services.due_phrase import english_due_phrase


def test_hindi_deadlines_become_english():
    assert english_due_phrase("आज") == "today"
    assert english_due_phrase("कल") == "tomorrow"
    assert english_due_phrase("आज शाम तक") == "by this evening"
    assert english_due_phrase("साढ़े चार बजे") == "4:30"


def test_untranslatable_falls_back_to_the_resolved_date():
    assert english_due_phrase("अजीब शब्द", date(2026, 10, 9)) == "Fri 9 Oct"
    assert english_due_phrase("अजीब शब्द") is None


def test_english_is_untouched():
    assert english_due_phrase("by Friday, 5 PM") == "by Friday, 5 PM"
    assert english_due_phrase(None) is None


def test_either_unicode_form_of_nukta_letters():
    import unicodedata

    for form in ("NFC", "NFD"):
        assert english_due_phrase(unicodedata.normalize(form, "साढ़े चार बजे")) == "4:30"


def test_devanagari_names_become_the_teammate_they_sound_like():
    from app.services.latin_names import latin_name

    people = ["Sarthak", "Archit Gupta", "Astha Sethi"]
    assert latin_name("सार्थक", people) == "Sarthak"
    assert latin_name("अर्चित", people) == "Archit"
    assert latin_name("कमल", people) == "Kamal"
    assert latin_name("Astha", people) == "Astha"
