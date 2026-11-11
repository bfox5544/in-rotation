"""The discovery assistant (ADR 0014). The model is a scripted fake: no test calls Gemini or uses quota."""
import pytest

from conftest import rg_id
from test_accounts import CREDS, SIGN_UP, account
from test_api import ILLMATIC, LIQUID_SWORDS, MADVILLAINY, TPAB, ids, rate, session

from app.chat import service
from app.chat.provider import ProviderError, Reply, get_provider

RADIOHEAD = rg_id("Radiohead")
OK_COMPUTER, KID_A = rg_id("OK Computer"), rg_id("Kid A")


class FakeProvider:
    """Runs a scripted list of tool calls through the real tools, then answers with fixed text."""
    model = "fake-model"

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.text = "Here you go."
        self.error: ProviderError | None = None
        self.seen: list[dict] = []
        self.results: list[dict] = []

    async def respond(self, system, history, tools, run_tool, max_calls):
        self.seen.append({"system": system, "history": history, "tools": [t.name for t in tools]})
        if self.error:
            raise self.error
        self.results = [await run_tool(name, args) for name, args in self.calls]
        return Reply(self.text, calls=len(self.calls) + 1)


@pytest.fixture()
def fake(client):
    from app.main import app
    provider = FakeProvider()
    app.dependency_overrides[get_provider] = lambda: provider
    service.reset_limits()
    yield provider
    app.dependency_overrides.pop(get_provider, None)
    service.reset_limits()


def ask(client, h, message, conversation=None):
    return client.post("/api/chat", json={"conversationId": conversation, "message": message}, headers=h)


def liked_hip_hop(client) -> dict[str, str]:
    h = session(client)
    for album_id in (ILLMATIC, MADVILLAINY, TPAB):
        rate(client, h, album_id, 5)
    return h


def test_assistant_is_off_without_a_key(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_provider.cache_clear()
    assert client.get("/api/chat/status").json()["enabled"] is False
    r = ask(client, session(client), "hi")
    assert r.status_code == 503 and "GEMINI_API_KEY" in r.json()["detail"]
    get_provider.cache_clear()


def test_recommendations_come_from_the_engine_with_the_same_exclusions(client, fake):
    h = liked_hip_hop(client)
    fake.calls = [("recommend_albums", {"count": 3})]
    r = ask(client, h, "Recommend 3 albums similar to my favorites")
    assert r.status_code == 200
    reply = r.json()["messages"][1]
    for_you = ids(client.get("/api/me/recommendations", params={"limit": 3}, headers=h).json()["items"])
    assert ids(reply["albums"]) == for_you and LIQUID_SWORDS in for_you    # cards = the engine's list
    assert not {ILLMATIC, MADVILLAINY, TPAB} & set(for_you)                 # rated albums never come back
    first = fake.results[0]["albums"][0]
    closest = first["why"]["most_similar_query_albums"]
    assert closest[0]["your_rating"] == 5 and 0 < closest[0]["share_of_score"] <= 1   # grounded in the user's own ratings
    assert "listeners who have a query album also have it" in first["why"]["listeners"]


def test_the_prompt_has_a_compact_taste_summary_and_no_identifiers(client, fake):
    h = liked_hip_hop(client)
    rate(client, h, rg_id("Kind of Blue"), 1.5)
    client.post("/api/account/register", json=SIGN_UP, headers=h)
    ask(client, h, "hi")
    system = fake.seen[0]["system"]
    assert "Illmatic by Nas (5 stars)" in system and "Disliked: Kind of Blue" in system and "hip hop" in system
    user_id = client.get("/api/me", headers=h).json()
    assert CREDS["email"].lower() not in system and "Bearer" not in system and str(user_id) not in system


def test_queried_albums_and_artists_are_not_recommended_back(client, fake):
    h = session(client)
    fake.calls = [("recommend_albums", {"like_album_ids": [ILLMATIC], "count": 5}),
                  ("recommend_albums", {"like_artist_ids": [RADIOHEAD], "popularity": "less_known"})]
    ask(client, h, "Something like Illmatic, then something like Radiohead but less mainstream")
    like_album, like_artist = fake.results
    assert ILLMATIC not in ids(like_album["albums"]) and "Illmatic" in like_album["basis"]
    similar = ids(client.get(f"/api/albums/{ILLMATIC}").json()["similar"])
    assert ids(like_album["albums"]) == similar[:5]                            # same engine as "Listeners also love"
    assert like_artist["albums"] and all(a["artist"] != "Radiohead" for a in like_artist["albums"])
    assert like_artist["popularity"] == "less_known"


def test_filters_and_bad_arguments_go_back_to_the_model(client, fake):
    h = liked_hip_hop(client)
    fake.calls = [("recommend_albums", {"genre": "Hip-Hop", "count": 3}), ("recommend_albums", {"genre": "polka"}),
                  ("recommend_albums", {"popularity": "obscure"}), ("recommend_albums", {"year_from": 2020}),
                  ("recommend_albums", {"like_album_ids": ["made-up"]}), ("no_such_tool", {})]
    ask(client, h, "more hip hop please")
    hip_hop, polka, obscure, later, made_up, unknown = fake.results
    assert ids(hip_hop["albums"]) == [LIQUID_SWORDS]                          # spelling-insensitive genre
    assert "No genre called 'polka'" in polka["error"] and "popularity must be" in obscure["error"]
    assert later["albums"] == [] and "note" in later        # no test album is from 2020 or later
    assert "Unknown album ids" in made_up["error"] and "no tool" in unknown["error"]


def test_search_and_album_details(client, fake):
    h = session(client)
    rate(client, h, OK_COMPUTER, 4.5)
    fake.calls = [("search_catalog", {"query": "radiohead"}), ("get_album_details", {"album_id": KID_A})]
    fake.text = "Kid A is the one."
    reply = ask(client, h, "Tell me about Kid A").json()["messages"][1]
    search, details = fake.results
    assert {a["artist"] for a in search["albums"]} == {"Radiohead"} and search["artists"][0]["name"] == "Radiohead"
    assert details["tracks"]["count"] == 3 and details["tracks"]["titles"][0] == "Everything in Its Right Place"
    assert ids(reply["albums"]) == [KID_A]


def test_follow_ups_see_earlier_messages_and_skip_albums_already_shown(client, fake):
    h = liked_hip_hop(client)
    fake.calls = [("recommend_albums", {"count": 2})]
    first = ask(client, h, "Recommend two albums").json()
    shown = ids(first["messages"][1]["albums"])
    conv = first["conversation"]["id"]
    ask(client, h, "Give me something less mainstream", conv)
    history = fake.seen[1]["history"]
    assert [t.role for t in history] == ["user", "assistant", "user"]
    assert history[1].text == "Here you go."                                   # what was said, nothing added
    system = fake.seen[1]["system"]
    assert all(f"(id {a})" in system for a in shown) and "Answer 1 (the latest):" in system   # "those" can resolve
    assert not set(shown) & set(ids(fake.results[0]["albums"]))                # refinements bring new albums
    got = client.get(f"/api/chat/conversations/{conv}", headers=h).json()
    assert [m["role"] for m in got["messages"]] == ["user", "assistant"] * 2


def test_save_to_lists_only_touches_the_users_own_lists(client, fake):
    a, b = session(client), session(client)
    client.post("/api/me/lists", json={"name": "Mix"}, headers=b)
    fake.calls = [("save_albums", {"album_ids": [ILLMATIC, KID_A]}),
                  ("save_albums", {"album_ids": [ILLMATIC], "list_name": "mix"}),
                  ("save_albums", {"album_ids": [OK_COMPUTER], "list_name": "Late night", "create_list": True})]
    reply = ask(client, a, "Add these to my listen later list").json()["messages"][1]
    later, other_users_list, created = fake.results
    assert later == {"list": "Listen later", "added": 2, "already_there": 0, "created_list": False}
    assert "No list called 'mix'" in other_users_list["error"]                # B's list is invisible to A
    assert created["created_list"] and reply["action"]["listName"] == "Late night"
    lib_a, lib_b = (client.get("/api/me/library", headers=h).json() for h in (a, b))
    assert set(ids(lib_a["later"])) == {ILLMATIC, KID_A} and [l["name"] for l in lib_a["lists"]] == ["Late night"]
    assert lib_b["later"] == [] and lib_b["lists"][0]["albums"] == []


def test_making_a_playlist_saves_every_recommendation_to_a_new_list(client, fake):
    h = liked_hip_hop(client)
    fake.calls = [("recommend_albums", {"count": 3, "save_to_list": "Late Night Picks"})]
    reply = ask(client, h, "Make me a playlist").json()["messages"][1]
    result = fake.results[0]
    picked = ids(result["albums"])
    assert picked and result["saved"] == {"list": "Late Night Picks", "added": len(picked), "already_there": 0, "created_list": True}
    assert ids(reply["albums"]) == picked                                         # the cards are the saved albums
    assert reply["action"]["createdList"] and reply["action"]["albumIds"] == picked
    lists = client.get("/api/me/library", headers=h).json()["lists"]
    assert [(l["name"], set(ids(l["albums"]))) for l in lists] == [("Late Night Picks", set(picked))]
    assert "save_to_list" in fake.seen[0]["system"]


def test_conversations_are_private(client, fake):
    a, b = session(client), session(client)
    conv = ask(client, a, "hello").json()["conversation"]["id"]
    assert client.get(f"/api/chat/conversations/{conv}", headers=b).status_code == 404
    assert client.delete(f"/api/chat/conversations/{conv}", headers=b).status_code == 404
    assert ask(client, b, "hijack", conv).status_code == 404
    assert client.get("/api/chat/conversations", headers=b).json() == []
    assert [c["id"] for c in client.get("/api/chat/conversations", headers=a).json()] == [conv]
    assert client.delete(f"/api/chat/conversations/{conv}", headers=a).status_code == 204
    assert client.get("/api/chat/conversations", headers=a).json() == []


def test_sign_in_keeps_this_browsers_chats(client, fake):
    account(client)
    other = session(client)
    conv = ask(client, other, "hello").json()["conversation"]["id"]
    token = client.post("/api/account/login", json=CREDS, headers=other).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert [c["id"] for c in client.get("/api/chat/conversations", headers=h).json()] == [conv]


@pytest.mark.parametrize("kind,status", [("quota", 429), ("rate", 429), ("unavailable", 503), ("blocked", 422), ("invalid", 502)])
def test_provider_errors_become_clear_messages(client, fake, kind, status):
    h = session(client)
    fake.error = ProviderError(kind, "x", calls=1)
    r = ask(client, h, "hello")
    assert r.status_code == status and r.json()["detail"] == service.ERRORS[kind][1]


def test_a_used_up_quota_stops_calls_until_it_resets(client, fake):
    h = session(client)
    fake.error = ProviderError("quota", "x", calls=1)
    ask(client, h, "hello")
    fake.error = None
    r = ask(client, h, "hello again")
    assert r.status_code == 429 and len(fake.seen) == 1                       # no second request to the provider


def test_failed_turns_count_but_are_left_out_of_the_history(client, fake):
    h = session(client)
    conv = ask(client, h, "first").json()["conversation"]["id"]
    fake.error = ProviderError("unavailable", "x", calls=3)
    assert ask(client, h, "this one fails", conv).status_code == 503
    fake.error = None
    ask(client, h, "third", conv)
    assert [t.text for t in fake.seen[-1]["history"]] == ["first", "Here you go.", "third"]


def test_limits(client, fake, monkeypatch):
    h = session(client)
    assert ask(client, h, "x" * (service.MAX_CHARS + 1)).status_code == 422
    assert ask(client, h, "   ").status_code == 422
    monkeypatch.setenv("INROTATION_CHAT_PER_MINUTE", "2")
    assert [ask(client, h, "hi").status_code for _ in range(3)] == [200, 200, 429]
    monkeypatch.setenv("INROTATION_CHAT_PER_MINUTE", "100")
    monkeypatch.setenv("GEMINI_DAILY_CALLS", str(2 + service.MAX_CALLS - 1))   # 2 used; a message may need MAX_CALLS more
    other = session(client)
    r = ask(client, other, "hi")
    assert r.status_code == 429 and "today's request limit" in r.json()["detail"]


def test_daily_limit_per_account_survives_deleting_chats(client, fake, monkeypatch):
    monkeypatch.setenv("INROTATION_CHAT_PER_DAY", "2")
    h = session(client)
    first = ask(client, h, "hi").json()["conversation"]["id"]
    assert ask(client, h, "again", first).status_code == 200
    r = ask(client, h, "one more")
    assert r.status_code == 429 and "today's 2 messages" in r.json()["detail"]
    assert client.delete(f"/api/chat/conversations/{first}", headers=h).status_code == 204
    assert ask(client, h, "after deleting").status_code == 429        # deleting chats doesn't give messages back


def test_daily_limit_per_device_covers_new_browsers(client, fake, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv("INROTATION_CHAT_PER_DEVICE_PER_DAY", "3")
    home = TestClient(app, client=("203.0.113.7", 50000))
    assert [ask(home, session(home), "hi").status_code for _ in range(3)] == [200, 200, 200]   # three fresh browsers
    r = ask(home, session(home), "a fourth browser")
    assert r.status_code == 429 and "This device" in r.json()["detail"]
    elsewhere = TestClient(app, client=("198.51.100.20", 50000))
    assert ask(elsewhere, session(elsewhere), "hi").status_code == 200


def test_device_keys_never_hold_the_address():
    key = service.device_key("203.0.113.7")
    assert key.startswith("d:") and "203.0.113" not in key and key == service.device_key("203.0.113.7")
    assert key != service.device_key("203.0.113.8")
    # IPv6: one /64 is one device
    assert service.device_key("2001:db8:1:2::10") == service.device_key("2001:db8:1:2:abcd::1")
    assert service.device_key("2001:db8:1:2::10") != service.device_key("2001:db8:1:3::10")
    assert service.device_key(None) is None


def test_tool_saves_are_undone_when_the_turn_fails(client, monkeypatch, fake):
    h = session(client)

    async def save_then_fail(system, history, tools, run_tool, max_calls):
        await run_tool("save_albums", {"album_ids": [ILLMATIC]})
        raise ProviderError("unavailable", "x", calls=2)
    monkeypatch.setattr(fake, "respond", save_then_fail)
    assert ask(client, h, "save Illmatic").status_code == 503
    assert client.get("/api/me/library", headers=h).json()["later"] == []    # the user never saw a confirmation


def test_compare_listeners_counts_overlap_and_flags_the_reference_itself(client, fake):
    h = session(client)
    fake.calls = [("compare_listeners", {"album_ids": [OK_COMPUTER, KID_A, ILLMATIC], "reference_artist_id": RADIOHEAD}),
                  ("compare_listeners", {"album_ids": [LIQUID_SWORDS, KID_A], "reference_album_id": ILLMATIC}),
                  ("compare_listeners", {"album_ids": [KID_A]})]
    ask(client, h, "Which of those is most like Radiohead?")
    by_artist, by_album, neither = fake.results
    assert [a.get("is_reference") for a in by_artist["albums"]] == [True, True, None]
    assert by_artist["albums"][2]["also_have_reference"] == 0                  # hip hop and rock listeners don't overlap
    liquid, kid_a = by_album["albums"]
    assert liquid["also_have_reference"] > 0 and kid_a["also_have_reference"] == 0
    assert "exactly one" in neither["error"]


def test_album_id_notes_never_reach_the_page(client, fake, database):
    h = liked_hip_hop(client)
    fake.calls = [("recommend_albums", {"count": 2})]
    fake.text = ("Two picks for you.\n\n(Albums shown:\n- Liquid Swords by GZA [id 3f3a6d95-326e-4384-80b0-0744f20f24ff]\n"
                 "- Untrue by Burial [id 002db1af-2e15-4e83-8feb-5aa8d9612f18])")
    reply = ask(client, h, "two albums").json()
    assert reply["messages"][1]["text"] == "Two picks for you."
    fake.text = "Try Untrue (id 002db1af-2e15-4e83-8feb-5aa8d9612f18), it's great."
    assert ask(client, h, "one more", reply["conversation"]["id"]).json()["messages"][1]["text"] == "Try Untrue, it's great."
    # An answer stored before the fix is cleaned when the conversation is opened again.
    from sqlalchemy import create_engine, text
    engine = create_engine(database)
    with engine.begin() as db:
        db.execute(text("UPDATE chat_messages SET content = :c WHERE id = :i"),
                   {"c": "Old answer.\n\n(Albums shown:\n- X by Y [id 002db1af-2e15-4e83-8feb-5aa8d9612f18])", "i": reply["messages"][1]["id"]})
    engine.dispose()
    got = client.get(f"/api/chat/conversations/{reply['conversation']['id']}", headers=h).json()
    assert got["messages"][1]["text"] == "Old answer."


def test_replies_never_show_semicolons():
    from app.chat.service import clean_reply
    assert clean_reply("Try Kid A; it's moodier.") == "Try Kid A. It's moodier."
    assert clean_reply("dream pop;shoegaze") == "dream pop,shoegaze"
