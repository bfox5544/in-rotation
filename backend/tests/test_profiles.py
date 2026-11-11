"""User profiles (ADR 0018): every account is a profile; public is the owner's choice."""
from io import BytesIO

from PIL import Image

from test_accounts import CREDS
from test_api import ILLMATIC, MADVILLAINY, TPAB, ids, rate, session


def member(client, email="listener@example.com", username="Night_Owl", name="Night Owl", public=False,
           ratings=((ILLMATIC, 5), (TPAB, 4))) -> dict[str, str]:
    h = session(client)
    for album_id, stars in ratings:
        rate(client, h, album_id, stars)
    r = client.post("/api/account/register", headers=h, json={
        "email": email, "password": CREDS["password"], "username": username, "displayName": name, "public": public})
    assert r.status_code == 200, r.text
    return h


def edit(client, h, username="night_owl", name="Night Owl", public=True):
    return client.put("/api/me/profile", json={"username": username, "displayName": name, "public": public}, headers=h)


def image(fmt="PNG", size=(600, 300), exif=False) -> bytes:
    img = Image.new("RGB", size, (242, 184, 75))
    out = BytesIO()
    if exif:
        data = Image.Exif()
        data[0x010F] = "Phone Maker"              # Make
        img.save(out, fmt, exif=data)
    else:
        img.save(out, fmt)
    return out.getvalue()


def test_an_account_is_a_profile_and_starts_private(client):
    h = member(client)
    assert client.get("/api/me", headers=h).json()["profile"] == \
        {"username": "night_owl", "displayName": "Night Owl", "avatarUrl": None, "public": False}
    assert client.get("/api/users/night_owl", headers=session(client)).status_code == 404
    own = client.get("/api/users/Night_Owl", headers=h).json()                 # usernames ignore case
    assert own["isYou"] is True and own["public"] is False


def test_anonymous_users_have_no_profile(client):
    h = session(client)
    assert client.get("/api/me", headers=h).json()["profile"] is None
    assert edit(client, h).status_code == 403


def test_a_public_profile(client):
    h = member(client, public=True)
    visitor = session(client)
    page = client.get("/api/users/night_owl", headers=visitor).json()
    assert page["displayName"] == "Night Owl" and page["isYou"] is False
    assert [(r["album"]["id"], r["rating"]) for r in page["ratings"]] == [(TPAB, 4), (ILLMATIC, 5)]   # newest first
    assert "email" not in page and "listener" not in str(page)
    assert client.get("/api/users/night_owl").status_code == 200             # no session needed


def test_owners_choose_public_or_private(client):
    h = member(client)
    assert edit(client, h, public=True).json()["public"] is True
    assert client.get("/api/users/night_owl").status_code == 200
    edit(client, h, public=False)
    for viewer in (session(client), {}):
        assert client.get("/api/users/night_owl", headers=viewer).status_code == 404
        assert client.get("/api/users/night_owl/insights", headers=viewer).status_code == 404
    assert client.get("/api/users/nobody_here").json() == client.get("/api/users/night_owl").json()   # same 404
    assert client.get("/api/users/night_owl/insights", headers=h).status_code == 200


def test_username_and_name_rules(client):
    h, other = member(client), member(client, "second@example.com", username="second")
    assert edit(client, h, username="ab").status_code == 422
    assert edit(client, h, username="no spaces").status_code == 422
    assert edit(client, h, name="   ").status_code == 422
    assert edit(client, h, name="x" * 41).status_code == 422
    assert edit(client, h, username="@Taken_Name", name="  Two \n Words ").json()["displayName"] == "Two Words"
    assert edit(client, other, username="TAKEN_NAME").status_code == 409
    assert edit(client, h, username="taken_name", name="Renamed").status_code == 200     # your own name is fine
    assert edit(client, h, username="renamed").status_code == 200
    assert edit(client, other, username="taken_name").status_code == 200                 # freed by the rename
    assert client.delete("/api/me/profile", headers=h).status_code == 405                # a profile goes with its account


def test_public_insights_leave_out_private_things(client):
    h = member(client, public=True)
    client.put(f"/api/me/later/{MADVILLAINY}", headers=h)
    client.get("/api/me/recommendations", params={"limit": 2}, headers=h)
    mine = client.get("/api/me/insights", headers=h).json()
    assert mine["overview"]["albumsRated"] == 2 and mine["recommendations"]["shown"] >= 1     # the save isn't in the profile
    public = client.get("/api/users/night_owl/insights", headers=session(client)).json()
    o = public["overview"]
    assert o["albumsRated"] == 2 and public["genres"] == mine["genres"]        # the same profile, from ratings
    assert public["recommendations"] is None
    assert MADVILLAINY not in ids(r["album"] for r in public["recentAlbums"])


def test_profile_picture_is_cropped_resized_and_stripped(client):
    h = member(client, public=True)
    r = client.put("/api/me/profile/picture", content=image("JPEG", (900, 400), exif=True),
                   headers={**h, "Content-Type": "image/jpeg"})
    assert r.status_code == 200, r.text
    url = r.json()["avatarUrl"]
    served = client.get(url)
    assert served.status_code == 200 and served.headers["content-type"] == "image/webp"
    assert "immutable" in served.headers["cache-control"]
    pic = Image.open(BytesIO(served.content))
    assert pic.format == "WEBP" and pic.size == (256, 256) and not pic.getexif() and "exif" not in pic.info

    replaced = client.put("/api/me/profile/picture", content=image(), headers=h).json()["avatarUrl"]
    assert replaced != url and client.get(url).status_code == 404          # the old file is gone
    assert client.get("/api/users/night_owl").json()["avatarUrl"] == replaced
    assert client.delete("/api/me/profile/picture", headers=h).json()["avatarUrl"] is None
    assert client.get(replaced).status_code == 404


def test_bad_pictures_are_refused(client):
    h = member(client)
    assert client.put("/api/me/profile/picture", content=image(), headers=session(client)).status_code == 403
    assert client.put("/api/me/profile/picture", content=b"<svg></svg>", headers=h).status_code == 422
    assert client.put("/api/me/profile/picture", content=b"", headers=h).status_code == 422
    assert client.put("/api/me/profile/picture", content=image("BMP"), headers=h).status_code == 422
    assert client.put("/api/me/profile/picture", content=b"0" * (8 * 1024 * 1024 + 1), headers=h).status_code == 413
    assert client.get("/api/avatars/..%2F..%2Fsecret.webp").status_code == 404
    assert client.get("/api/avatars/not-a-real-file.webp").status_code == 404
