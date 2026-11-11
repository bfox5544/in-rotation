"""User profiles (ADR 0018): the account *is* the profile. Creating an account picks a username and a
name; the page at /u/{username} shows the person's picture, ratings and Insights built from ratings only.

Anonymous users have no profile (their library lives in one browser). Profiles start private: only the
owner sees the page until they make it public; anyone else gets the same 404 as for a username that
doesn't exist.
Emails, user ids, listen later, lists, dismissals and recommendation stats never appear on a profile.

Pictures are re-encoded here (Pillow): cropped to a square, 256 px, WebP, with every bit of metadata
(EXIF, GPS) dropped. Files get random names, so replacing a picture changes its URL.
"""
import os
import re
import secrets
import unicodedata
import warnings
from datetime import datetime
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from . import insights
from .auth import CurrentUser, OptionalUser
from .catalog import get_catalog
from .db import DB
from .schema import Rating, User

router = APIRouter(prefix="/api")

USERNAME = re.compile(r"^[a-z0-9_]{3,20}$")
MAX_NAME = 40
MAX_UPLOAD = 8 * 1024 * 1024        # bytes
MAX_PIXELS = 40_000_000             # refuse anything bigger before decoding it (decompression bombs)
AVATAR_SIZE = 256
FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
_AVATAR_FILE = re.compile(r"^[A-Za-z0-9_-]{16}\.webp$")


def avatar_dir() -> Path:
    root = Path(__file__).resolve().parents[2]
    return Path(os.environ.get("INROTATION_AVATARS", str(root / "data" / "avatars")))


def avatar_url(user: User) -> str | None:
    return f"/api/avatars/{user.avatar}" if user.avatar else None


class ProfileFields(BaseModel):
    username: str = Field(max_length=40)
    displayName: str = Field(max_length=200)
    public: bool = False


class MyProfile(BaseModel):
    username: str
    displayName: str
    avatarUrl: str | None
    public: bool


class PublicProfile(BaseModel):
    username: str
    displayName: str
    avatarUrl: str | None
    memberSince: datetime
    isYou: bool
    public: bool
    ratings: list[insights.RatedAlbum]       # newest first


def my_profile(user: User) -> MyProfile | None:
    if not user.username:
        return None
    return MyProfile(username=user.username, displayName=user.display_name or user.username,
                     avatarUrl=avatar_url(user), public=user.profile_public)


def clean_name(name: str) -> str:
    name = " ".join("".join(c for c in name if unicodedata.category(c)[0] != "C").split())
    if not 1 <= len(name) <= MAX_NAME:
        raise HTTPException(422, f"Use a name of 1 to {MAX_NAME} characters")
    return name


def clean_username(username: str) -> str:
    username = username.strip().lower().lstrip("@")
    if not USERNAME.match(username):
        raise HTTPException(422, "Use 3 to 20 letters, numbers or underscores for your username")
    return username


def _account(user: User) -> None:
    if not user.email:
        raise HTTPException(403, "Create an account to make a profile")


def _visible(db: Db, username: str, viewer: User | None) -> User:
    user = db.scalar(select(User).where(User.username == username.strip().lower()))
    if user is None or (not user.profile_public and (viewer is None or viewer.id != user.id)):
        raise HTTPException(404, "Profile not found")
    return user


def _remove_avatar(user: User) -> None:
    if user.avatar:
        (avatar_dir() / user.avatar).unlink(missing_ok=True)
        user.avatar = None


def encode_avatar(data: bytes) -> bytes:
    """Any common image -> a 256 px square WebP with no metadata. 422 if it isn't one."""
    bad = HTTPException(422, "Choose a JPEG, PNG, WebP or GIF image")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(BytesIO(data))
            if img.format not in FORMATS:
                raise bad
            if img.width * img.height > MAX_PIXELS:
                raise HTTPException(422, "That image is too large. Try one under 40 megapixels")
            img.load()                               # first frame of an animated image
            img = ImageOps.exif_transpose(img)       # phones store rotation in EXIF, which is dropped below
            img = img.convert("RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB")
            img = ImageOps.fit(img, (AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS)
            out = BytesIO()
            img.save(out, "WEBP", quality=85, method=4)
            return out.getvalue()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
        raise bad from e


# --- your own profile ----------------------------------------------------------------------------

@router.get("/me/profile", response_model=MyProfile | None)
def get_my_profile(user: CurrentUser) -> MyProfile | None:
    return my_profile(user)


def check_profile(db: Db, user: User, fields: ProfileFields) -> tuple[str, str]:
    """Validated (username, name), or 422/409. Usernames are unique regardless of case."""
    username, name = clean_username(fields.username), clean_name(fields.displayName)
    if db.scalar(select(User.id).where(User.username == username, User.id != user.id)):
        raise HTTPException(409, "That username is taken")
    return username, name


def apply_profile(user: User, username: str, name: str, public: bool) -> None:
    user.username, user.display_name, user.profile_public = username, name, public


@router.put("/me/profile", response_model=MyProfile)
def save_profile(body: ProfileFields, user: CurrentUser, db: DB) -> MyProfile:
    """Edit your profile (or, for an account made before profiles existed, set it up)."""
    _account(user)
    apply_profile(user, *check_profile(db, user, body), body.public)
    return my_profile(user)


@router.put("/me/profile/picture", response_model=MyProfile)
async def upload_picture(request: Request, user: CurrentUser, db: DB) -> MyProfile:
    """The request body is the image itself (any image content type)."""
    _account(user)
    if not user.username:
        raise HTTPException(409, "Choose a username first")
    if int(request.headers.get("content-length") or 0) > MAX_UPLOAD:
        raise HTTPException(413, "That image is over 8 MB")
    data = await request.body()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "That image is over 8 MB")
    if not data:
        raise HTTPException(422, "Choose an image")
    encoded = encode_avatar(data)
    folder = avatar_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_urlsafe(12)}.webp"
    (folder / name).write_bytes(encoded)
    _remove_avatar(user)
    user.avatar = name
    return my_profile(user)


@router.delete("/me/profile/picture", response_model=MyProfile)
def delete_picture(user: CurrentUser) -> MyProfile:
    _account(user)
    if not user.username:
        raise HTTPException(404, "No profile")
    _remove_avatar(user)
    return my_profile(user)


@router.get("/avatars/{name}")
def avatar(name: str) -> FileResponse:
    path = avatar_dir() / name
    if not _AVATAR_FILE.match(name) or not path.is_file():
        raise HTTPException(404, "Not found")
    # Names are random and change with every upload, so the file never changes under its name.
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})


# --- anyone's profile ----------------------------------------------------------------------------

@router.get("/users/{username}", response_model=PublicProfile)
def profile(username: str, viewer: OptionalUser, db: DB) -> PublicProfile:
    user = _visible(db, username, viewer)
    rows = db.execute(select(Rating.album_id, Rating.half_stars).where(Rating.user_id == user.id)
                      .order_by(Rating.updated_at.desc())).all()
    catalog = get_catalog()
    stars: dict[str, float] = {}
    for (_, half), album_id in zip(rows, catalog.canonical_each([r[0] for r in rows])):
        stars.setdefault(album_id, half / 2)
    return PublicProfile(username=user.username, displayName=user.display_name or user.username,
                         avatarUrl=avatar_url(user), memberSince=user.created_at,
                         isYou=viewer is not None and viewer.id == user.id, public=user.profile_public,
                         ratings=[insights.RatedAlbum(album=a, rating=stars[a.id]) for a in catalog.get_many(list(stars))])


@router.get("/users/{username}/insights", response_model=insights.Insights)
def profile_insights(username: str, viewer: OptionalUser, db: DB) -> insights.Insights:
    return insights.build(db, _visible(db, username, viewer), public=True)

