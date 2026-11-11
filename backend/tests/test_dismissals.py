from conftest import rg_id
from test_accounts import CREDS, account
from test_api import ILLMATIC, LIQUID_SWORDS, MADVILLAINY, TPAB, ids, rate, session
from test_artists import AMNESIAC, OLD_AMNESIAC


def recs(client, h, limit: int = 24) -> list[str]:
    return ids(client.get("/api/me/recommendations", params={"limit": limit}, headers=h).json()["items"])


def dismiss(client, h, album_id: str, on: bool = True) -> int:
    return client.request("PUT" if on else "DELETE", f"/api/me/dismissed/{album_id}", headers=h).status_code


def test_dismissed_albums_leave_for_you_and_the_list_refills(client):
    h = session(client)
    for album_id in (ILLMATIC, MADVILLAINY, TPAB):
        rate(client, h, album_id, 5)
    before = recs(client, h, limit=3)
    assert before[0] == LIQUID_SWORDS
    assert dismiss(client, h, LIQUID_SWORDS) == 204 and dismiss(client, h, LIQUID_SWORDS) == 204   # idempotent
    after = recs(client, h, limit=3)
    assert LIQUID_SWORDS not in after and len(after) >= len(before) and after[:len(before) - 1] == before[1:]
    assert dismiss(client, h, LIQUID_SWORDS, on=False) == 204                                   # undo
    assert recs(client, h, limit=3) == before


def test_dismissals_also_apply_to_the_popularity_fallback(client):
    h = session(client)
    top = recs(client, h)[0]
    dismiss(client, h, top)
    assert top not in recs(client, h)


def test_dismissal_validation_privacy_and_merges(client):
    a, b = session(client), session(client)
    assert dismiss(client, a, "nope") == 404
    dismiss(client, a, OLD_AMNESIAC)                                         # stored under the current id
    assert AMNESIAC not in recs(client, a) and AMNESIAC in recs(client, b, limit=60)
    assert dismiss(client, a, AMNESIAC, on=False) == 204 and AMNESIAC in recs(client, a, limit=60)


def test_sign_in_keeps_this_browsers_dismissals(client):
    account(client)
    other = session(client)
    top = recs(client, other)[0]
    dismiss(client, other, top)
    token = client.post("/api/account/login", json=CREDS, headers=other).json()["token"]
    assert top not in recs(client, {"Authorization": f"Bearer {token}"}, limit=60)
