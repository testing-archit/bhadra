"""Pure-Python coverage for attendee normalization.

Deliberately free of database fixtures: the normalization rules are where the
subtle bugs live (dedup keys, bare emails, dropped junk), and they are worth
testing on a machine that cannot reach the database.
"""

import uuid

from app.services import attendee_service


def test_bare_strings_become_named_attendees():
    assert attendee_service.normalize_input(["Ravi", "Avni"]) == [
        {"user_id": None, "name": "Ravi", "email": None},
        {"user_id": None, "name": "Avni", "email": None},
    ]


def test_a_bare_email_string_is_used_as_both_name_and_email():
    assert attendee_service.normalize_input(["guest@vendor.com"]) == [
        {"user_id": None, "name": "guest@vendor.com", "email": "guest@vendor.com"}
    ]


def test_emails_are_lowercased_and_names_are_trimmed():
    assert attendee_service.normalize_input([{"name": "  Guest  ", "email": "G@Ext.COM"}]) == [
        {"user_id": None, "name": "Guest", "email": "g@ext.com"}
    ]


def test_an_object_with_only_an_email_falls_back_to_it_for_the_name():
    assert attendee_service.normalize_input([{"email": "x@y.com"}]) == [
        {"user_id": None, "name": "x@y.com", "email": "x@y.com"}
    ]


def test_duplicates_are_dropped_case_insensitively():
    assert attendee_service.normalize_input(["Ravi", "ravi", "RAVI"]) == [
        {"user_id": None, "name": "Ravi", "email": None}
    ]


def test_user_id_wins_over_name_as_the_dedup_key():
    user_id = str(uuid.uuid4())
    result = attendee_service.normalize_input(
        [{"user_id": user_id, "name": "Ravi"}, {"name": "Ravi"}]
    )
    assert [item["user_id"] for item in result] == [user_id, None]


def test_blank_and_non_dict_entries_are_dropped():
    assert attendee_service.normalize_input(["", "   ", 42, None, {}, {"name": ""}]) == []


def test_input_is_capped_so_a_hostile_client_cannot_flood_the_table():
    names = [f"Person {index}" for index in range(attendee_service.MAX_ATTENDEES + 25)]
    assert len(attendee_service.normalize_input(names)) == attendee_service.MAX_ATTENDEES


def test_none_input_is_tolerated():
    assert attendee_service.normalize_input(None) == []
