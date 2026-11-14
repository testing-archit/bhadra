from unittest.mock import patch

# Imported at collection time: conftest patches the module attribute for
# every test, and this file tests the real function.
from app.services.contradiction_service import check_for_contradiction


def test_no_readable_past_meetings_means_no_lookup():
    with patch("app.services.contradiction_service.qdrant_service.search") as search:
        assert check_for_contradiction("Use Postgres", "Engineering", meeting_ids=[]) == {"note": None, "usage": None}
    search.assert_not_called()


def test_lookup_is_limited_to_the_given_meetings():
    with patch("app.services.contradiction_service.qdrant_service.search", return_value=[]) as search:
        check_for_contradiction("Use Postgres", "Engineering", meeting_ids=["m1"])
    assert search.call_args.kwargs["meeting_ids"] == ["m1"]
