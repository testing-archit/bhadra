from unittest.mock import patch

from tests.conftest import auth_headers


async def test_chat_attendee_scoped_search(client, member_user):
    """A member with no meetings of their own gets an empty attendee-scoped
    id list, not the old department-wide scope."""
    with patch("app.services.memory_retriever.answer_query") as mock_answer:
        mock_answer.return_value = {"answer": "test answer", "sources": [], "usage": {"input_tokens": 0, "cache_tokens_read": 0, "cache_tokens_written": 0, "output_tokens": 0}}
        response = await client.post(
            "/api/chat", json={"query": "why did we do X?"}, headers=auth_headers(member_user)
        )
    assert response.status_code == 200
    mock_answer.assert_called_once_with("why did we do X?", [], 8, [])


async def test_chat_admin_searches_only_their_own_meetings(client, admin_user, other_member_user, make_meeting):
    # Admins see every meeting from the Admin panel, but their own memory
    # chat answers from their meetings only, like everyone else's.
    await make_meeting(other_member_user, "Someone else's meeting", "Sales")
    with patch("app.services.memory_retriever.answer_query") as mock_answer:
        mock_answer.return_value = {"answer": "test answer", "sources": [], "usage": {"input_tokens": 0, "cache_tokens_read": 0, "cache_tokens_written": 0, "output_tokens": 0}}
        response = await client.post(
            "/api/chat", json={"query": "why did we do X?"}, headers=auth_headers(admin_user)
        )
    assert response.status_code == 200
    mock_answer.assert_called_once_with("why did we do X?", [], 8, [])


async def test_chat_passes_recent_conversation_history(client, member_user):
    history = [
        {"role": "user", "content": "What did we decide about Project Atlas?"},
        {"role": "assistant", "content": "The team selected the phased rollout."},
    ]
    with patch("app.services.memory_retriever.answer_query") as mock_answer:
        mock_answer.return_value = {"answer": "Because risk was lower.", "sources": [], "usage": {"input_tokens": 0, "cache_tokens_read": 0, "cache_tokens_written": 0, "output_tokens": 0}}
        response = await client.post(
            "/api/chat",
            json={"query": "Why?", "history": history},
            headers=auth_headers(member_user),
        )
    assert response.status_code == 200
    mock_answer.assert_called_once_with("Why?", [], 8, history)


async def test_chat_meeting_scoped_non_attendee_denied(client, member_user, other_member_user, make_meeting):
    sales_meeting = await make_meeting(other_member_user, "Private Sales Chat Meeting", "Sales")

    response = await client.post(
        "/api/chat",
        json={"query": "why?", "meeting_id": str(sales_meeting.id)},
        headers=auth_headers(member_user),
    )
    assert response.status_code == 404


async def test_chat_meeting_scoped_attendee_allowed(client, member_user, make_meeting):
    eng_meeting = await make_meeting(member_user, "Own Eng Chat Meeting", "Engineering")

    with patch("app.services.memory_retriever.answer_query_for_meeting") as mock_answer:
        mock_answer.return_value = {"answer": "test answer", "sources": [], "usage": {"input_tokens": 0, "cache_tokens_read": 0, "cache_tokens_written": 0, "output_tokens": 0}}
        response = await client.post(
            "/api/chat",
            json={"query": "why?", "meeting_id": str(eng_meeting.id)},
            headers=auth_headers(member_user),
        )
    assert response.status_code == 200
    mock_answer.assert_called_once()


async def test_chat_meeting_scoped_admin_can_access_any_department(
    client, admin_user, other_member_user, make_meeting
):
    sales_meeting = await make_meeting(other_member_user, "Admin Access Sales Meeting", "Sales")

    with patch("app.services.memory_retriever.answer_query_for_meeting") as mock_answer:
        mock_answer.return_value = {"answer": "test answer", "sources": [], "usage": {"input_tokens": 0, "cache_tokens_read": 0, "cache_tokens_written": 0, "output_tokens": 0}}
        response = await client.post(
            "/api/chat",
            json={"query": "why?", "meeting_id": str(sales_meeting.id)},
            headers=auth_headers(admin_user),
        )
    assert response.status_code == 200


async def test_memory_chat_is_saved_and_can_be_reloaded(client, member_user):
    with patch("app.services.memory_retriever.answer_query") as mock_answer:
        mock_answer.return_value = {
            "answer": "The team selected the phased rollout.",
            "sources": [{
                "meeting_id": None,
                "meeting_title": "Atlas planning",
                "meeting_date": "2026-08-12T00:00:00+00:00",
                "content_type": "summary",
            }],
            "usage": {"input_tokens": 0, "cache_tokens_read": 0, "cache_tokens_written": 0, "output_tokens": 0},
        }
        response = await client.post(
            "/api/chat",
            json={"query": "What did we decide about Project Atlas?"},
            headers=auth_headers(member_user),
        )

    assert response.status_code == 200
    conversation_id = response.json()["conversation_id"]

    conversations = await client.get(
        "/api/chat/conversations", headers=auth_headers(member_user)
    )
    assert conversations.status_code == 200
    assert any(item["id"] == conversation_id for item in conversations.json())

    detail = await client.get(
        f"/api/chat/conversations/{conversation_id}", headers=auth_headers(member_user)
    )
    assert detail.status_code == 200
    assert [message["role"] for message in detail.json()["messages"]] == ["user", "assistant"]
    assert detail.json()["messages"][1]["sources"][0]["meeting_title"] == "Atlas planning"


async def test_memory_chat_conversation_is_private_and_deletable(
    client, member_user, other_member_user
):
    with patch("app.services.memory_retriever.answer_query") as mock_answer:
        mock_answer.return_value = {
            "answer": "Saved answer",
            "sources": [],
            "usage": {"input_tokens": 0, "cache_tokens_read": 0, "cache_tokens_written": 0, "output_tokens": 0},
        }
        created = await client.post(
            "/api/chat", json={"query": "Save this chat"}, headers=auth_headers(member_user)
        )
    conversation_id = created.json()["conversation_id"]

    denied = await client.get(
        f"/api/chat/conversations/{conversation_id}", headers=auth_headers(other_member_user)
    )
    assert denied.status_code == 404

    deleted = await client.delete(
        f"/api/chat/conversations/{conversation_id}", headers=auth_headers(member_user)
    )
    assert deleted.status_code == 200
    missing = await client.get(
        f"/api/chat/conversations/{conversation_id}", headers=auth_headers(member_user)
    )
    assert missing.status_code == 404
