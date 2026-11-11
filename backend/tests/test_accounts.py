from conftest import rg_id
from test_api import ILLMATIC, LIQUID_SWORDS, MADVILLAINY, TPAB, ids, rate, session

UNTRUE, BLONDE, DUMMY = rg_id("Untrue"), rg_id("Blonde"), rg_id("Dummy")
CREDS = {"email": "Listener@Example.com", "password": "correct horse"}
SIGN_UP = {**CREDS, "username": "listener", "displayName": "Listener"}   # an account is a profile (ADR 0018)


def library(client, h) -> dict:
    lib = client.get("/api/me/library", headers=h).json()
    return {"rated": {r["album"]["id"]: r["rating"] for r in lib["rated"]}, "later": ids(lib["later"]),
            "lists": {lst["name"]: ids(lst["albums"]) for lst in lib["lists"]}}


def account(client) -> dict[str, str]:
    """A signed-up user with one rated and one listen-later album."""
    h = session(client)
    rate(client, h, ILLMATIC, 4.5)
    client.put(f"/api/me/later/{UNTRUE}", headers=h)
    assert client.post("/api/account/register", json=SIGN_UP, headers=h).status_code == 200
    return h


def test_sign_up_keeps_the_anonymous_library(client):
    h = account(client)
    assert client.get("/api/me", headers=h).json() == {"email": "listener@example.com", "profile": {   # email stored lowercased
        "username": "listener", "displayName": "Listener", "avatarUrl": None, "public": False}}
    assert library(client, h) == {"rated": {ILLMATIC: 4.5}, "later": [UNTRUE], "lists": {}}


def test_sign_up_validation(client):
    h = session(client)
    assert client.post("/api/account/register", json={**SIGN_UP, "email": "nope", "password": "long enough"}, headers=h).status_code == 422
    assert client.post("/api/account/register", json={**SIGN_UP, "email": "a@b.co", "password": "short"}, headers=h).status_code == 422
    assert client.post("/api/account/register", json=SIGN_UP).status_code == 401              # needs a session
    taken = account(client)
    assert client.post("/api/account/register", json={**SIGN_UP, "username": "fresh"}, headers=h).json()["detail"].startswith("An account")
    assert client.post("/api/account/register", json={**SIGN_UP, "email": "new@b.co"}, headers=h).json()["detail"] == "That username is taken"
    assert client.post("/api/account/register", json={**SIGN_UP, "email": "new@b.co", "username": "x"}, headers=h).status_code == 422
    assert client.post("/api/account/register", json={**SIGN_UP, "email": "new@b.co", "username": "fresh", "displayName": " "}, headers=h).status_code == 422
    assert client.get("/api/me", headers=h).json() == {"email": None, "profile": None}     # a refused sign-up changes nothing
    assert client.post("/api/account/register", json={**SIGN_UP, "email": "x@y.co", "username": "other"}, headers=taken).status_code == 409


def test_sign_in_rejects_bad_credentials_with_one_message(client):
    account(client)
    wrong = client.post("/api/account/login", json={**CREDS, "password": "wrong password"})
    unknown = client.post("/api/account/login", json={**CREDS, "email": "who@example.com"})
    assert wrong.status_code == unknown.status_code == 401 and wrong.json() == unknown.json()


def test_sign_in_elsewhere_merges_that_browsers_library(client):
    first = account(client)
    other = session(client)                                   # another browser, anonymous
    for album_id in (ILLMATIC, MADVILLAINY):                  # Illmatic is already rated: the account's 4.5 stays
        rate(client, other, album_id, 3)
    client.put(f"/api/me/later/{UNTRUE}", headers=other)
    trip = client.post("/api/me/lists", json={"name": "Road trip"}, headers=other).json()["id"]
    client.put(f"/api/me/lists/{trip}/albums/{BLONDE}", headers=other)

    resp = client.post("/api/account/login", json={**CREDS, "email": " LISTENER@example.com "}, headers=other)
    signed_in = {"Authorization": f"Bearer {resp.json()['token']}"}
    lib = library(client, signed_in)
    assert lib["rated"] == {ILLMATIC: 4.5, MADVILLAINY: 3} and lib["later"] == [UNTRUE]
    assert lib["lists"] == {"Road trip": [BLONDE]}
    assert library(client, first) == lib                      # same account in both browsers
    assert client.get("/api/me/library", headers=other).status_code == 401   # the anonymous user is gone


def test_sign_in_without_a_session_and_sign_out(client):
    account(client)
    h = {"Authorization": f"Bearer {client.post('/api/account/login', json=CREDS).json()['token']}"}
    assert library(client, h)["rated"] == {ILLMATIC: 4.5}
    assert client.post("/api/account/logout", headers=h).status_code == 204
    assert client.get("/api/me", headers=h).status_code == 401


def test_lists_create_fill_rename_delete(client):
    h = session(client)
    created = client.post("/api/me/lists", json={"name": "  Late   night "}, headers=h)
    assert created.status_code == 201 and created.json()["name"] == "Late night"
    lid = created.json()["id"]
    for album_id in (UNTRUE, DUMMY, UNTRUE):                  # adding twice is a no-op
        assert client.put(f"/api/me/lists/{lid}/albums/{album_id}", headers=h).status_code == 204
    assert library(client, h)["lists"] == {"Late night": [DUMMY, UNTRUE]}   # newest first
    assert client.patch(f"/api/me/lists/{lid}", json={"name": "3am"}, headers=h).json()["name"] == "3am"
    client.delete(f"/api/me/lists/{lid}/albums/{DUMMY}", headers=h)
    assert library(client, h)["lists"] == {"3am": [UNTRUE]}
    assert client.delete(f"/api/me/lists/{lid}", headers=h).status_code == 204
    assert library(client, h)["lists"] == {}


def test_lists_are_private_and_validated(client):
    a, b = session(client), session(client)
    lid = client.post("/api/me/lists", json={"name": "Mine"}, headers=a).json()["id"]
    assert client.put(f"/api/me/lists/{lid}/albums/{UNTRUE}", headers=b).status_code == 404
    assert client.delete(f"/api/me/lists/{lid}", headers=b).status_code == 404
    assert client.put(f"/api/me/lists/{lid}/albums/nope", headers=a).status_code == 404
    assert client.post("/api/me/lists", json={"name": "   "}, headers=a).status_code == 422


def test_recommendations_skip_albums_on_any_list(client):
    h = session(client)
    for album_id in (ILLMATIC, MADVILLAINY):
        rate(client, h, album_id)
    lid = client.post("/api/me/lists", json={"name": "Have it"}, headers=h).json()["id"]
    client.put(f"/api/me/lists/{lid}/albums/{LIQUID_SWORDS}", headers=h)
    got = ids(client.get("/api/me/recommendations", headers=h).json()["items"])
    assert got and LIQUID_SWORDS not in got and TPAB in got


def test_new_sessions_and_accounts_are_limited_per_device(client, monkeypatch):
    """Without the preview password a script could fill the database, so each network address may start
    LIMITS["session"] sessions an hour and create LIMITS["register"] accounts a day (keyed hashes only)."""
    from datetime import timedelta

    from app import auth
    monkeypatch.setattr(auth, "LIMITS", {"session": (3, timedelta(hours=1)), "register": (1, timedelta(days=1))})
    tokens = [client.post("/api/session").json()["token"] for _ in range(3)]
    refused = client.post("/api/session")
    assert refused.status_code == 429 and "network" in refused.json()["detail"]
    first, second = ({"Authorization": f"Bearer {t}"} for t in tokens[:2])
    assert client.post("/api/account/register", json=SIGN_UP, headers=first).status_code == 200
    other = {**SIGN_UP, "email": "second@example.com", "username": "second"}
    assert client.post("/api/account/register", json=other, headers=second).status_code == 429
