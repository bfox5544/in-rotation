"""POST /api/feedback: messages from the Contact page (ADR 0020), kept in Postgres.

Read them with `python -m app.feedback` from backend/ (newest first; `--limit N`). There is no admin
page: the site has no admin accounts. Each browser can send FEEDBACK_PER_HOUR messages an hour.
"""
import argparse
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .auth import CurrentUser, clean_email
from .db import DB
from .schema import Feedback, now

router = APIRouter(prefix="/api")

FEEDBACK_PER_HOUR = 5
MAX_MESSAGE = 2000
Topic = Literal["feedback", "recommendations", "data", "bug", "other"]


class FeedbackIn(BaseModel):
    topic: Topic = "feedback"
    message: str = Field(max_length=MAX_MESSAGE * 2)
    replyTo: str | None = Field(default=None, max_length=254)


@router.post("/feedback", status_code=204)
def send_feedback(body: FeedbackIn, user: CurrentUser, db: DB) -> None:
    message = body.message.strip()
    if not 1 <= len(message) <= MAX_MESSAGE:
        raise HTTPException(422, f"Write a message of up to {MAX_MESSAGE:,} characters")
    reply_to = clean_email(body.replyTo) if body.replyTo and body.replyTo.strip() else None
    recent = db.scalar(select(func.count()).select_from(Feedback)
                       .where(Feedback.user_id == user.id, Feedback.created_at >= now() - timedelta(hours=1)))
    if recent >= FEEDBACK_PER_HOUR:
        raise HTTPException(429, "Thanks for all the feedback. Try again in an hour")
    db.add(Feedback(user_id=user.id, topic=body.topic, message=message, reply_to=reply_to))


def main() -> None:
    from .db import get_engine
    p = argparse.ArgumentParser(description="Print Contact page messages, newest first.")
    p.add_argument("--limit", type=int, default=20)
    limit = p.parse_args().limit
    with get_engine().connect() as conn:
        rows = conn.execute(select(Feedback).order_by(Feedback.created_at.desc()).limit(limit)).all()
    for r in rows:
        print(f"#{r.id}  {r.created_at:%Y-%m-%d %H:%M}  {r.topic}  reply to: {r.reply_to or 'none'}\n{r.message}\n")
    if not rows:
        print("No feedback yet.")


if __name__ == "__main__":
    main()
