"""Anonymous sessions (ADR 0002) and optional email accounts on top of them (ADR 0006).

Every visitor is a user row from their first save. Signing up attaches an email and password to
that same row, so the library is kept. Signing in from another browser issues a new session for
the account and folds that browser's anonymous library into it.
"""
import base64
import hashlib
import hmac
import re
import secrets
from datetime import timedelta, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session as Db

from .db import DB
from .limits import email_key
from .schema import (CUSTOM, LISTEN_LATER, Conversation, Dismissal, Impression, List, ListItem, LoginFailure, RateEvent, Rating,
                     Session, User, now)

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SCRYPT = {"n": 2**14, "r": 8, "p": 1}       # about 16 MB and 50 ms per hash
MIN_PASSWORD = 8

# Sign-in limits: failed password checks in the last FAILURE_WINDOW, per email and per device (network address).
FAILURE_WINDOW = timedelta(minutes=15)
FAILURES_PER_EMAIL = 5
FAILURES_PER_DEVICE = 20
# Limits per device on things a script could repeat to fill the database (rate_events): (count, window).
LIMITS = {"session": (30, timedelta(hours=1)),      # new anonymous sessions: a browser makes one, a private window another
          "register": (5, timedelta(days=1))}       # new accounts
SEEN_EVERY = timedelta(days=1)          # how often users.last_seen_at is refreshed


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **SCRYPT)
    b64 = lambda b: base64.b64encode(b).decode()
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    _, n, r, p, salt, digest = stored.split("$")
    got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), dklen=32, n=int(n), r=int(r), p=int(p))
    return hmac.compare_digest(got, base64.b64decode(digest))


# Checked against when the email is unknown, so a miss takes as long as a wrong password.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def new_session(db: Db, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    db.add(Session(token_hash=hash_token(token), user_id=user_id))
    return token


def create_anonymous_user(db: Db) -> str:
    """Create a user with no personal data (and its listen-later list); return a session token."""
    user = User()
    db.add(user)
    db.flush()
    db.add(List(user_id=user.id, name="Listen later", kind=LISTEN_LATER))
    return new_session(db, user.id)


def _session_user(db: Db, authorization: str | None) -> User | None:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    user = db.scalar(select(User).join(Session).where(Session.token_hash == hash_token(token)))
    seen = user.last_seen_at if user is not None else None
    if seen is not None and seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)       # SQLite gives back naive times (stored as UTC)
    if user is not None and (seen is None or seen < now() - SEEN_EVERY):
        user.last_seen_at = now()       # at most one write a day per user; the request's commit saves it
    return user


def current_user(db: DB, authorization: Annotated[str | None, Header()] = None) -> User:
    if not (authorization or "").strip():
        raise HTTPException(401, "Missing session token")
    user = _session_user(db, authorization)
    if user is None:
        raise HTTPException(401, "Unknown session")
    return user


def optional_user(db: DB, authorization: Annotated[str | None, Header()] = None) -> User | None:
    return _session_user(db, authorization)


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]


def clean_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > 254 or not EMAIL.match(email):
        raise HTTPException(422, "Enter a valid email address")
    return email


def check_password(password: str) -> None:
    if not MIN_PASSWORD <= len(password) <= 256:
        raise HTTPException(422, f"Use a password of at least {MIN_PASSWORD} characters")


def register(db: Db, user: User, email: str, password: str) -> None:
    """Attach credentials to the current (anonymous) user, keeping everything they saved."""
    if user.email:
        raise HTTPException(409, "You are already signed in")
    email = clean_email(email)
    check_password(password)
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists. Sign in instead")
    user.email, user.password_hash = email, hash_password(password)


TOO_MANY = "Too many attempts. Wait 15 minutes, then try again."
LIMIT_MESSAGES = {"session": "Too many new visits from this network. Try again in an hour.",
                  "register": "Too many new accounts from this network today. Try again tomorrow."}


def allow(db: Db, action: str, device: str | None) -> None:
    """Count one `action` for this device, or refuse with 429 once it has done LIMITS[action] in the window.
    Without a known address (tests, local tools) nothing is counted."""
    if not device:
        return
    limit, window = LIMITS[action]
    done = db.scalar(select(func.count()).select_from(RateEvent)
                     .where(RateEvent.action == action, RateEvent.key == device, RateEvent.at >= now() - window))
    if done >= limit:
        raise HTTPException(429, LIMIT_MESSAGES[action])
    db.execute(delete(RateEvent).where(RateEvent.at < now() - timedelta(days=1)))
    db.add(RateEvent(action=action, key=device))


def _failures(db: Db, key: str) -> int:
    return db.scalar(select(func.count()).select_from(LoginFailure)
                     .where(LoginFailure.key == key, LoginFailure.at >= now() - FAILURE_WINDOW))


def check_attempts(db: Db, email: str, device: str | None) -> None:
    """Refuse before checking the password once an email or a device has failed too often recently."""
    if _failures(db, email_key(email)) >= FAILURES_PER_EMAIL or (device and _failures(db, device) >= FAILURES_PER_DEVICE):
        raise HTTPException(429, TOO_MANY)


def record_failure(db: Db, email: str, device: str | None) -> None:
    """Count a failed password check. Committed at once, because the request then ends with an error (no commit)."""
    db.rollback()
    db.add_all([LoginFailure(key=k) for k in (email_key(email), device) if k])
    db.execute(delete(LoginFailure).where(LoginFailure.at < now() - FAILURE_WINDOW))
    db.commit()


def authenticate(db: Db, email: str, password: str, device: str | None = None) -> User:
    check_attempts(db, email, device)
    account = db.scalar(select(User).where(User.email == email.strip().lower()))
    stored = account.password_hash if account and account.password_hash else None
    if not verify_password(password, stored or _DUMMY_HASH) or not stored:
        record_failure(db, email, device)
        raise HTTPException(401, "Email or password is incorrect")
    db.execute(delete(LoginFailure).where(LoginFailure.key == email_key(email)))   # a success clears this email's count
    return account


def merge_into(db: Db, anon: User, account: User) -> None:
    """Move an anonymous user's ratings, lists, dismissals, assistant chats and recommendation history into an account, then delete the anonymous user."""
    later = lambda u: db.scalar(select(List).where(List.user_id == u.id, List.kind == LISTEN_LATER))
    src, dst = later(anon), later(account)
    if src and dst:
        saved = select(ListItem.album_id).where(ListItem.list_id == dst.id).scalar_subquery()
        db.execute(update(ListItem).where(ListItem.list_id == src.id, ListItem.album_id.not_in(saved)).values(list_id=dst.id))
    db.execute(update(List).where(List.user_id == anon.id, List.kind == CUSTOM).values(user_id=account.id))
    rated = select(Rating.album_id).where(Rating.user_id == account.id).scalar_subquery()   # the account's own ratings win
    db.execute(update(Rating).where(Rating.user_id == anon.id, Rating.album_id.not_in(rated)).values(user_id=account.id))
    hidden = select(Dismissal.album_id).where(Dismissal.user_id == account.id).scalar_subquery()
    db.execute(update(Dismissal).where(Dismissal.user_id == anon.id, Dismissal.album_id.not_in(hidden)).values(user_id=account.id))
    db.execute(update(Conversation).where(Conversation.user_id == anon.id).values(user_id=account.id))
    seen = select(Impression.album_id).where(Impression.user_id == account.id).scalar_subquery()
    db.execute(update(Impression).where(Impression.user_id == anon.id, Impression.album_id.not_in(seen)).values(user_id=account.id))
    db.execute(delete(User).where(User.id == anon.id))   # cascades to its sessions and what is left


def delete_account(db: Db, user: User, password: str, device: str | None = None) -> None:
    """Delete an account and everything in it, after checking its password. Wrong passwords count toward the
    sign-in limits, so this can't be used to guess one."""
    if not user.email or not user.password_hash:
        raise HTTPException(403, "Only accounts can be deleted. This browser's library goes when you clear its data.")
    check_attempts(db, user.email, device)
    if not verify_password(password, user.password_hash):
        record_failure(db, user.email, device)
        raise HTTPException(403, "That password is incorrect")   # not 401: the session itself is fine
    db.execute(delete(LoginFailure).where(LoginFailure.key == email_key(user.email)))
    db.execute(delete(User).where(User.id == user.id))   # cascades to sessions, ratings, lists, chats and the rest
