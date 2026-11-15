from scripts.evaluate_telephony import aggregate, normalize, score


def test_wer_counts_insertions_deletions_and_substitutions():
    assert score("one two three", "one four three five")["word_errors"] == 2
    assert score("one two three", "one three")["deletions"] == 1
    assert score("one two", "one two")["wer"] == 0


def test_hindi_combining_marks_and_critical_digits_survive():
    assert normalize("कृपया, भुगतान करें!") == "कृपया भुगतान करें"
    assert score("send 1500 to Archit", "send 150 to archit", ["1500", "Archit"])["entity_hits"] == 1


def test_silence_hallucinations_are_not_hidden_by_zero_word_denominator():
    result = score("", "thanks for watching")
    assert result["wer"] is None and result["silence_hallucinated_words"] == 3


def test_corpus_wer_uses_word_weighting():
    result = aggregate([score("one", "wrong"), score("one two three", "one two three")])
    assert result["wer"] == .25
