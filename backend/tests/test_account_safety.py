"""Deleting an account, the sign-in limits and the anonymous-user cleanup (owner request 2026-11-07)."""
from datetime import timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session as Db

from test_accounts import CREDS, SIGN_UP, account
from test_api import ILLMATIC, rate, session

from app import auth, cleanup
from app.db import get_engine
from app.schema import LoginFailure, User, now


def sign_in(client, password, email=CREDS["email"], h=None):
    return client.post("/api/account/login", json={"email": email, "password": password}, headers=h or {})


def remove(client, h, password):
    return client.request("DELETE", "/api/account", json={"password": password}, headers=h)


def test_deleting_an_account_removes_everything(client):
    h = account(client)
    other = sign_in(client, CREDS["password"]).json()["token"]              # a second browser signed in to it
    assert remove(client, h, "wrong password").status_code == 403
    assert client.get("/api/me", headers=h).status_code == 200                # a wrong password changes nothing
    assert remove(client, h, CREDS["password"]).status_code == 204
    assert client.get("/api/me", headers=h).status_code == 401                # both sessions are gone
    assert client.get("/api/me", headers={"Authorization": f"Bearer {other}"}).status_code == 401
    assert client.get("/api/users/listener").status_code == 404
    assert sign_in(client, CREDS["password"]).status_code == 401
    with Db(get_engine()) as db:
        assert db.scalar(select(User).where(User.email == "listener@example.com")) is None
    fresh = session(client)                                                   # the email and username are free again
    assert client.post("/api/account/register", json=SIGN_UP, headers=fresh).status_code == 200


def test_anonymous_users_cannot_delete(client):
    assert remove(client, session(client), "anything").status_code == 403


def test_sign_in_is_limited_per_email(client):
    account(client)
    assert [sign_in(client, "nope").status_code for _ in range(auth.FAILURES_PER_EMAIL)] == [401] * auth.FAILURES_PER_EMAIL
    r = sign_in(client, CREDS["password"])                                    # even the right password waits now
    assert r.status_code == 429 and "15 minutes" in r.json()["detail"]
    with Db(get_engine()) as db:                                              # 15 minutes later
        db.execute(update(LoginFailure).values(at=now() - auth.FAILURE_WINDOW - timedelta(seconds=1)))
        db.commit()
    assert sign_in(client, CREDS["password"]).status_code == 200
    assert sign_in(client, "nope").status_code == 401                         # a success started the count again
    with Db(get_engine()) as db:                                              # emails are stored as keyed hashes only
        keys = list(db.scalars(select(LoginFailure.key)))
        assert keys and all("example" not in k for k in keys)


def test_sign_in_is_limited_per_device(client, monkeypatch):
    monkeypatch.setattr(auth, "FAILURES_PER_DEVICE", 3)
    account(client)
    assert [sign_in(client, "nope", f"guess{i}@example.com").status_code for i in range(3)] == [401] * 3
    assert sign_in(client, CREDS["password"]).status_code == 429             # this device is paused
    from fastapi.testclient import TestClient
    from app.main import app
    elsewhere = TestClient(app, client=("198.51.100.20", 50000))
    assert sign_in(elsewhere, CREDS["password"]).status_code == 200


def test_cleanup_removes_only_old_anonymous_users(client):
    def user_of(h):
        with Db(get_engine()) as db:
            return db.scalar(select(User.id).order_by(User.created_at.desc()))
    made = {}
    for name in ("empty_old", "empty_recent", "saved_old", "saved_ancient"):
        h = session(client)
        client.get("/api/me/library", headers=h)
        if name.startswith("saved"):
            rate(client, h, ILLMATIC, 4)
        made[name] = user_of(h)
    acct = account(client)
    made["account"] = user_of(acct)
    unseen = {"empty_old": 8, "empty_recent": 2, "saved_old": 100, "saved_ancient": 400, "account": 999}
    with Db(get_engine()) as db:
        for name, days in unseen.items():
            db.execute(update(User).where(User.id == made[name]).values(last_seen_at=now() - timedelta(days=days)))
        db.commit()
        assert cleanup.clean(db, dry_run=True) == 2
        assert db.scalar(select(User.id).where(User.id == made["empty_old"]))   # a dry run deletes nothing
        assert cleanup.clean(db) == 2
        left = set(db.scalars(select(User.id)))
    assert made["empty_old"] not in left and made["saved_ancient"] not in left
    assert {made["empty_recent"], made["saved_old"], made["account"]} <= left


def test_requests_refresh_last_seen(client):
    h = session(client)
    client.get("/api/me", headers=h)
    with Db(get_engine()) as db:
        db.execute(update(User).values(last_seen_at=now() - timedelta(days=30)))
        db.commit()
    client.get("/api/me", headers=h)
    with Db(get_engine()) as db:
        seen = db.scalar(select(User.last_seen_at))
        seen = seen if seen.tzinfo else seen.replace(tzinfo=timezone.utc)
        assert seen > now() - timedelta(minutes=5)


def test_cleanup_prunes_expired_rate_limit_rows(client):
    """The Privacy page says the keyed hashes behind the limits go within two days, even with no new traffic."""
    from datetime import date

    from app.schema import ChatUsage, RateEvent
    with Db(get_engine()) as db:
        db.add_all([LoginFailure(key="d:old", at=now() - timedelta(hours=1)), LoginFailure(key="d:new"),
                    RateEvent(action="session", key="d:old", at=now() - timedelta(days=2)), RateEvent(action="session", key="d:new"),
                    ChatUsage(day=date.today() - timedelta(days=5), key="d:old", messages=1),
                    ChatUsage(day=date.today(), key="d:new", messages=1)])
        db.commit()
        assert cleanup.prune_limits(db) == 3
        keys = [*db.scalars(select(LoginFailure.key)), *db.scalars(select(RateEvent.key)), *db.scalars(select(ChatUsage.key))]
    assert keys == ["d:new"] * 3
