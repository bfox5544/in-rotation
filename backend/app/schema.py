"""User data tables (PostgreSQL; SQLite works too for quick tests). Migrations: backend/migrations.

Album ids are release-group MBIDs from the read-only catalog (data/catalog.db), so they are plain
strings here, not foreign keys. Design and deviations from the M6 target schema: ADR 0006.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

LISTEN_LATER, CUSTOM = "listen_later", "custom"


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)        # lowercased; NULL = anonymous
    password_hash: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # Profile (ADR 0018): accounts only. username is lowercase and unique; NULL = no profile.
    username: Mapped[str | None] = mapped_column(String(20), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(40))
    avatar: Mapped[str | None] = mapped_column(String(40))                     # file name in the avatar folder
    profile_public: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Last request with this user's session, updated at most once a day (for app.cleanup). NULL = created_at.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class Session(Base):
    """One row per signed-in browser. Only the SHA-256 of the token is stored."""
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class List(Base):
    """Listen later (one per user, created with the user) and the user's own named lists."""
    __tablename__ = "lists"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("one_listen_later_per_user", "user_id", unique=True,
              postgresql_where=text("kind = 'listen_later'"), sqlite_where=text("kind = 'listen_later'")),
    )


class ListItem(Base):
    __tablename__ = "list_items"
    list_id: Mapped[int] = mapped_column(ForeignKey("lists.id", ondelete="CASCADE"), primary_key=True)
    album_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Rating(Base):
    """0.5-5 stars, stored as whole half stars (1-10) so equality and ranges stay exact.
    Ratings are the only taste signal: they feed the recommendation query (recs.ratings) and
    below 3 stars only exclude the album (ADR 0008, 0009)."""
    __tablename__ = "user_ratings"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    album_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    half_stars: Mapped[int] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("half_stars BETWEEN 1 AND 10", name="half_stars_range"),)

    @property
    def stars(self) -> float:
        return self.half_stars / 2


class Dismissal(Base):
    """An album the user removed from For you. It is only excluded from recommendations, not
    treated as a dislike (same reasoning as low ratings, ADR 0008; ADR 0010)."""
    __tablename__ = "user_dismissals"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    album_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Conversation(Base):
    """A chat with the discovery assistant (ADR 0014). Only its owner can read it."""
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ChatMessage(Base):
    """One message. `albums` holds the catalog ids shown as cards (only ids the tools returned);
    `action` records a save so the page can offer Undo; `model_calls` counts the model requests a
    user message cost, for the daily budget."""
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(10))            # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text)
    albums: Mapped[list] = mapped_column(JSON, default=list)
    action: Mapped[dict | None] = mapped_column(JSON)
    model_calls: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    __table_args__ = (Index("chat_messages_by_conversation", "conversation_id", "id"),)


class Impression(Base):
    """An album first recommended to a user: on For you (or the home page's picks) or by the assistant.
    Only the first showing is kept, so later ratings and saves can be compared with it (ADR 0017)."""
    __tablename__ = "recommendation_impressions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    album_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(10))           # 'for_you' | 'ask'
    shown_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Feedback(Base):
    """A message from the Contact page (ADR 0020). The email is optional, only for a reply."""
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    topic: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    reply_to: Mapped[str | None] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class ChatUsage(Base):
    """Ask messages per Pacific day (the daily limits, ADR 0014). `key` is 'u:<user id>' for an account or browser,
    or 'd:<keyed hash>' for a network address (a device). Raw addresses are never stored, and rows older than
    yesterday are deleted. Counted here rather than from chat_messages so that deleting a chat doesn't reset it."""
    __tablename__ = "chat_usage"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    messages: Mapped[int] = mapped_column(Integer, default=0)


class RateEvent(Base):
    """Something a device did that is limited: starting an anonymous session ('session') or creating an account
    ('register'). `key` is the device's keyed hash (app/limits.py), never an address. Rows older than a day are
    deleted as new ones arrive (auth.allow)."""
    __tablename__ = "rate_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(16))
    key: Mapped[str] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    __table_args__ = (Index("rate_events_by_key", "action", "key", "at"),)


class LoginFailure(Base):
    """A failed password check (sign-in or account deletion), for the sign-in limits. `key` is an email ('e:') or a
    device ('d:'), both keyed hashes (app/limits.py). Rows older than the window are deleted as new ones arrive."""
    __tablename__ = "login_failures"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("login_failures_by_key", "key", "at"),)
