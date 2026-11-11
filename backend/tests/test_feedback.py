"""Contact page feedback (ADR 0020)."""
from sqlalchemy import select

from test_api import session


def stored(client):
    from app.db import get_engine
    from app.schema import Feedback
    with get_engine().connect() as conn:
        return conn.execute(select(Feedback.topic, Feedback.message, Feedback.reply_to).order_by(Feedback.id)).all()


def test_feedback_is_stored(client):
    h = session(client)
    assert client.post("/api/feedback", json={"topic": "data", "message": "  Missing cover for Untrue.  "}, headers=h).status_code == 204
    assert client.post("/api/feedback", json={"message": "Love it", "replyTo": "Me@Example.com"}, headers=h).status_code == 204
    assert stored(client) == [("data", "Missing cover for Untrue.", None), ("feedback", "Love it", "me@example.com")]


def test_feedback_validation_and_limits(client):
    h = session(client)
    assert client.post("/api/feedback", json={"message": "   "}, headers=h).status_code == 422
    assert client.post("/api/feedback", json={"message": "x" * 2001}, headers=h).status_code == 422
    assert client.post("/api/feedback", json={"message": "hi", "replyTo": "not an email"}, headers=h).status_code == 422
    assert client.post("/api/feedback", json={"message": "hi", "topic": "spam"}, headers=h).status_code == 422
    assert client.post("/api/feedback", json={"message": "hi"}).status_code == 401
    for _ in range(5):
        assert client.post("/api/feedback", json={"message": "hi"}, headers=h).status_code == 204
    assert client.post("/api/feedback", json={"message": "hi"}, headers=h).status_code == 429
    assert client.post("/api/feedback", json={"message": "hi"}, headers=session(client)).status_code == 204   # per browser
