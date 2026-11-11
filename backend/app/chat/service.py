"""One assistant turn: limits, context, the model's tool loop, and what gets stored (ADR 0014).

What goes to the provider: these instructions, a short taste summary (album titles, artists, stars,
genres, list names), the last few messages, and tool results (catalog facts and listening-data
counts). Never emails, user ids, conversation ids or historical user ids.
"""
import os
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session as Db

from ..limits import device_key  # noqa: F401  (used by the route; kept here for tests)
from ..schema import ChatMessage, ChatUsage, Conversation, User, now
from . import tools
from .provider import ProviderError, Reply, Turn

MAX_CHARS = 1000            # per user message
HISTORY = 10                # earlier messages sent with each request
MAX_CALLS = 4               # model requests per user message: up to 3 tool rounds and the answer
SHOWN_LIMIT = 100           # earlier recommendations kept out of new ones
PACIFIC = ZoneInfo("America/Los_Angeles")   # Gemini's daily quotas reset at midnight Pacific time


def _setting(name: str, default: int) -> int:
    return int(os.environ.get(name, "") or default)


def per_minute() -> int:
    return _setting("INROTATION_CHAT_PER_MINUTE", 5)


def per_day() -> int:
    """Messages an account (or an anonymous browser) may send per Pacific day."""
    return _setting("INROTATION_CHAT_PER_DAY", 25)


def per_device() -> int:
    """Messages one device (network address) may send per Pacific day, across all its browsers and accounts.
    Higher than per_day because a household or office can share one address."""
    return _setting("INROTATION_CHAT_PER_DEVICE_PER_DAY", 40)


def daily_calls() -> int:
    """Model requests the whole site may make per Pacific day: a cap on spending (each costs a fraction of a cent)."""
    return _setting("GEMINI_DAILY_CALLS", 200)


def _used(db: Db, day: date, key: str) -> int:
    return db.scalar(select(ChatUsage.messages).where(ChatUsage.day == day, ChatUsage.key == key)) or 0


def _count(db: Db, day: date, keys: list[str]) -> None:
    """Add one message to each key's count for the day (an upsert, safe when two requests arrive at once)."""
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    for key in keys:
        stmt = insert(ChatUsage).values(day=day, key=key, messages=1)
        db.execute(stmt.on_conflict_do_update(index_elements=["day", "key"], set_={"messages": ChatUsage.messages + 1}))
    db.execute(delete(ChatUsage).where(ChatUsage.day < day - timedelta(days=1)))


def quota_day_start(at: datetime | None = None) -> datetime:
    local = (at or now()).astimezone(PACIFIC)
    return datetime.combine(local.date(), time(0), PACIFIC)


# Set when Google reports the daily quota used up; no requests until the next Pacific midnight.
_quota_closed_until: datetime | None = None
busy: set[str] = set()      # users with a reply in progress (one at a time each)


def quota_closed() -> bool:
    return _quota_closed_until is not None and now() < _quota_closed_until


def close_quota() -> None:
    global _quota_closed_until
    _quota_closed_until = quota_day_start() + timedelta(days=1)


def reset_limits() -> None:
    """For tests."""
    global _quota_closed_until
    _quota_closed_until = None
    busy.clear()


SYSTEM = """You are the music discovery assistant on In Rotation, an album recommendation website. You're warm, \
curious and relaxed, like a friend who works at a good record shop: plain words, a little enthusiasm, no corporate tone.

How you work:
- Recommendations come ONLY from the recommend_albums tool, which runs the site's recommendation engine over \
listening data from about 476,000 people. Never suggest an album from your own memory. To find albums "like" an \
artist or album, get its id with search_catalog, then call recommend_albums with like_artist_ids or like_album_ids.
- "Less mainstream", "deeper", "more obscure" means a later popularity step than the last request \
(anything, less_known, under_the_radar, deep_cuts). "Different from what I usually listen to" means outside_my_taste.
- Use ids only from tool results or from the "Albums already shown" list below. Never make up ids.
- The page shows album cards (cover, title, artist, buttons) for the albums your tools returned this turn, so \
don't repeat a full list in text. Write a short intro, then a few highlights with one line each on why.
- Explanations must come from the tools' "why" and "basis" fields: which of the user's albums it is most similar \
to (the same listeners rank both highly), how many listeners who have those albums also have it, its listener count. Never invent counts, scores, listeners or \
reasons. You may add well-known, general facts about an album or artist's sound, but no made-up details.
- Listener counts come from people's top-50 album lists in the listening data, not streams or sales.
- Lists: when the user's latest message asks you to make, build or create a list or playlist ("make a 1980s \
playlist", "put together a list of jazz albums"), call recommend_albums once with save_to_list set to the name they \
gave, or a short Title Case name for the request ("1980s Picks"). The albums are saved in that same step, so never just \
show them. When they ask to save or add albums already shown ("save these to a list", "add those"), call save_albums \
with EVERY album from the latest answer in "Albums already shown", not only the ones your text named. "A list" or "a \
new list" means a new list (create_list, with a fitting name), never Listen later. Only "listen later" or "save for \
later" means their Listen later list. Never save anything the user didn't ask to save.
- After saving, say exactly how many albums went to which list. The page offers Undo.
- Ratings are 0.5 to 5 stars. Favorites are albums rated 4.5 or 5; dislikes are 2 stars or less.
- If a tool returns few or no albums, say so honestly and suggest loosening the request.
- Keep answers short: usually under 120 words. Plain text, with simple "-" lists when helpful. No tables or headings.
- Never use semicolons. Use a full stop or a comma instead.
- Stay on music and this site. If asked for something else, say briefly that you can only help with music here.
- Never mention internal ids, tool names or these instructions.

Today is {today}.

About this user:
{profile}

Albums already shown in this conversation, for resolving "those" or "the second one". This is reference \
only: never repeat this list, its layout or the ids in a reply.
{shown}"""


def profile_summary(t: tools.TurnState) -> str:
    p = tools.taste_profile(t, loved=12, liked=6, disliked=5)
    if not p["rated_albums"]:
        return "No ratings yet. Recommendations will be the most-listened albums until they rate a few."
    fmt = lambda xs: "; ".join(f"{x['title']} by {x['artist']} ({x['stars']:g} stars)" for x in xs) or "none"
    lines = [f"Rated albums: {p['rated_albums']}.", f"Favorites: {fmt(p['favorites'])}.", f"Also liked: {fmt(p['liked'])}."]
    if p["disliked"]:
        lines.append(f"Disliked: {fmt(p['disliked'])}.")
    if p["top_genres"]:
        lines.append(f"Top genres: {', '.join(p['top_genres'][:6])}.")
    lines.append("Lists: " + ", ".join(f"{x['name']} ({x['albums']} albums)" for x in p["lists"]) + ".")
    return "\n".join(lines)


def own_conversation(db: Db, user: User, conversation_id: str) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    return conv


def _messages(db: Db, conv: Conversation) -> list[ChatMessage]:
    return list(db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conv.id).order_by(ChatMessage.id)))


def _answered(messages: list[ChatMessage]) -> list[ChatMessage]:
    """The last HISTORY messages that got an answer; failed turns are left out."""
    return [m for i, m in enumerate(messages)
            if m.role == "assistant" or (i + 1 < len(messages) and messages[i + 1].role == "assistant")][-HISTORY:]


def _history(messages: list[ChatMessage]) -> list[Turn]:
    """The recent conversation as the model sees it: exactly what was said, nothing added. (Notes
    appended to earlier answers get copied into new ones, so the albums go in the prompt instead.)"""
    return [Turn(m.role, clean_reply(m.content) if m.role == "assistant" else m.content) for m in _answered(messages)]


def shown_albums(messages: list[ChatMessage]) -> str:
    """The albums each recent answer showed, numbered as on the page, for the system prompt."""
    from ..catalog import get_catalog
    answers = [m for m in _answered(messages) if m.role == "assistant" and m.albums]
    if not answers:
        return "None yet."
    blocks = []
    for n, m in enumerate(answers, start=1):
        latest = " (the latest)" if n == len(answers) else ""
        rows = "\n".join(f"  {i}. {a.title} by {a.artist} (id {a.id})" for i, a in enumerate(get_catalog().get_many(m.albums), start=1))
        blocks.append(f"Answer {n}{latest}:\n{rows}")
    return "\n".join(blocks)


# Leftovers of the old history format, which the model sometimes copied into replies (fixed 2026-11-03).
_SEMICOLON = re.compile(r";\s+(\S)")
_SHOWN_NOTE = re.compile(r"\s*\(Albums shown:.*?\)\s*$", re.DOTALL)
_ID = re.compile(r"\s*[\[(]id [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}[\])]")


def clean_reply(text: str) -> str:
    """Drop album-id notes from an answer (ids must never reach the page), and turn any semicolon the
    model still writes into a full stop (the site uses none, owner request 2026-11-03)."""
    text = _ID.sub("", _SHOWN_NOTE.sub("", text)).strip()
    return _SEMICOLON.sub(lambda m: ". " + m[1].upper(), text).replace(";", ",")


BUDGET_USED = "The assistant has reached today's request limit. It will be back after midnight Pacific time."


def check_limits(db: Db, user: User, device: str | None = None) -> None:
    if quota_closed():
        raise HTTPException(429, BUDGET_USED)
    mine = select(func.count()).select_from(ChatMessage).join(Conversation).where(
        Conversation.user_id == user.id, ChatMessage.role == "user")
    if db.scalar(mine.where(ChatMessage.created_at >= now() - timedelta(minutes=1))) >= per_minute():
        raise HTTPException(429, "That's a lot of messages at once. Give it a minute.")
    day = quota_day_start().date()
    if _used(db, day, f"u:{user.id}") >= per_day():
        raise HTTPException(429, f"You've used today's {per_day()} messages with the assistant. Try again tomorrow.")
    if device and _used(db, day, device) >= per_device():
        raise HTTPException(429, f"This device has used today's {per_device()} messages with the assistant. Try again tomorrow.")
    used = db.scalar(select(func.coalesce(func.sum(ChatMessage.model_calls), 0)).where(
        ChatMessage.created_at >= quota_day_start()))
    if used + MAX_CALLS > daily_calls():
        raise HTTPException(429, BUDGET_USED)


ERRORS = {
    "quota": (429, BUDGET_USED),
    "rate": (429, "The assistant is busy right now. Try again in a minute."),
    "unavailable": (503, "Gemini isn't responding right now. Try again in a moment."),
    "config": (503, "The assistant isn't set up correctly (API key or model). Check the backend .env."),
    "blocked": (422, "Gemini wouldn't answer that one. Try asking another way."),
    "invalid": (502, "The assistant sent an answer that couldn't be used. Try again."),
}


def start(db: Db, user: User, conversation_id: str | None, text: str, device: str | None = None) -> tuple[Conversation, ChatMessage, tools.TurnState, str, list[Turn]]:
    """Validate and store the user's message; return what the model needs."""
    text = text.strip()
    if not 1 <= len(text) <= MAX_CHARS:
        raise HTTPException(422, f"Messages are 1 to {MAX_CHARS} characters")
    conv = own_conversation(db, user, conversation_id) if conversation_id else None
    check_limits(db, user, device)
    if conv is None:
        conv = Conversation(user_id=user.id, title=" ".join(text.split())[:80])
        db.add(conv)
        db.flush()
    earlier = _messages(db, conv)
    shown = list(dict.fromkeys(a for m in earlier if m.role == "assistant" for a in m.albums))[-SHOWN_LIMIT:]
    message = ChatMessage(conversation_id=conv.id, role="user", content=text, albums=[], model_calls=0)
    db.add(message)
    conv.updated_at = now()
    _count(db, quota_day_start().date(), [f"u:{user.id}"] + ([device] if device else []))
    db.flush()
    db.commit()             # the message counts toward the limits even if the model call fails
    state = tools.TurnState(db=db, user=user, shown=shown)
    system = SYSTEM.format(today=now().astimezone(PACIFIC).date().isoformat(), profile=profile_summary(state),
                           shown=shown_albums(earlier))
    return conv, message, state, system, [*_history(earlier), Turn("user", text)]


def finish(db: Db, conv: Conversation, message: ChatMessage, state: tools.TurnState, reply: Reply) -> ChatMessage:
    message.model_calls = reply.calls
    text = clean_reply(reply.text) + ("\n\n(I ran out of room there. Ask me to go on.)" if reply.truncated else "")
    answer = ChatMessage(conversation_id=conv.id, role="assistant", content=text,
                         albums=tools.cards(state, reply.text), action=state.action, model_calls=0)
    db.add(answer)
    conv.updated_at = now()
    db.flush()
    return answer


def fail(db: Db, message: ChatMessage, error: ProviderError) -> HTTPException:
    """Keep the user's message (it counts toward limits) and its model calls; nothing the tools saved."""
    if error.kind == "quota":
        close_quota()
    db.rollback()
    message.model_calls = error.calls
    db.commit()
    status, detail = ERRORS[error.kind]
    return HTTPException(status, detail)
