# 0018: User profiles

Status: accepted (2026-11-03, owner request: "user profiles which will show a user's name, profile picture, ratings, and insights").

## What it is
**An account is a profile** (owner decision, 2026-11-03: "Profile should be the same as an account, users can decide whether to make their profile public"). Creating an account asks for a name and a username along with the email and password, and the account's page is `/u/{username}`: name, picture, ratings and Insights. There is no separate "make a profile" step and no deleting a profile apart from its account.
- **Header:** signed in, one **Profile** link with the picture (it replaced "Account"); otherwise **Sign In**.
- **Settings:** on your own profile a third tab, **Settings**, holds the picture, name, username, the Public Profile switch, the email you're signed in with and Sign Out. `/account` is sign-in and sign-up; signed in, it redirects to that tab.
- **Older accounts:** accounts made before profiles have no username. Their Profile link opens "Finish Your Profile" on `/account`.

## Decisions
- **Anonymous users have no profile.** Their library lives in one browser's storage, so a page built on it could vanish.
- **Private until the owner makes it public** (owner decision). Every account has a profile, so nobody's page appears without them choosing it: the sign-up form has a Public Profile checkbox, off by default, and Settings can switch it either way. A private profile gets everyone else the same 404 as a username that doesn't exist (no "this profile is private" leak). The owner always sees their own page, with a note when it is private.
- *First version, same day:* profiles were optional, made on the Account page, public by default, and deletable. Replaced by the above.
- **Ratings only.** The profile shows ratings and Insights built from ratings (`insights.build(public=True)`). Listen later, lists, dismissals and recommendation stats stay private, and so do the email and user id. The ratings are someone's public taste; the rest is a to-do list.
- **Usernames:** 3-20 of `a-z 0-9 _`, stored lowercase, unique, case-insensitive in URLs. They can change (old links then 404). **Names:** 1-40 characters, control characters dropped, whitespace collapsed.
- **Pronouns:** text about someone else uses their name ("Night Owl gravitates toward Dream Pop"), never a guessed pronoun.

## Profile pictures
- Uploaded as the raw request body (`PUT /api/me/profile/picture`), at most 8 MB; JPEG, PNG, WebP or GIF (first frame).
- **Re-encoded with Pillow (new dependency, `pillow>=11`):** EXIF rotation applied, then centre-cropped to a 256 px square and saved as WebP. Every bit of metadata (EXIF, GPS, camera) is dropped, so a phone photo can't leak where it was taken. Images over 40 megapixels are refused before decoding (decompression bombs). Anything Pillow can't read is a 422.
- Stored in `data/avatars` (`INROTATION_AVATARS`), git-ignored like the rest of `data/`, under a random file name (no user id). A new upload gets a new name and deletes the old file, so `GET /api/avatars/{name}` is cached as immutable for a year.
- With no picture, the first letter of the name on a plain tile.
- A deployment (M9) needs this folder on persistent storage or object storage, like the cover cache.

## Data (migration 0007)
`users` gains `username` (unique; NULL only for anonymous users and accounts made before profiles), `display_name`, `avatar` (file name) and `profile_public` (default false). No new table: one profile per account. Sign-in merging is unaffected, since anonymous users can't have a profile.

## API
| Method and path | Purpose |
|---|---|
| `GET /me` | now also `profile: {username, displayName, avatarUrl, public} \| null` |
| `POST /account/register` | now `{email, password, username, displayName, public}`; the username and name are checked first, so a refused sign-up changes nothing (409 username taken, 422 invalid) |
| `GET/PUT /me/profile` | read or update (`{username, displayName, public}`; 403 without an account, 409 username taken, 422 invalid). No DELETE: a profile goes with its account |
| `PUT/DELETE /me/profile/picture` | upload (body = image; 409 before a username exists, 413 over 8 MB, 422 not an image) or remove |
| `GET /avatars/{name}` | the WebP |
| `GET /users/{username}` | `{username, displayName, avatarUrl, memberSince, isYou, public, ratings: [{album, rating}]}`, newest first; no session needed |
| `GET /users/{username}/insights` | Insights from ratings only; `recommendations` is null |

## Page
- **Header:** picture, name, @username, "Member since November 2026". The owner gets Edit Profile (opens Settings) and Copy Link (when public), plus a note when the profile is private.
- **Ratings tab:** count, Newest First / Highest Rated, cards with the profile's stars as the caption; 48 at a time. On someone else's profile a line explains that the caption is their rating and the badge on the cover is yours.
- **Insights tab:** the Library Insights view, worded for the person by name, without Albums Saved or Recommendations; with fewer than 3 ratings it says so.
- **Settings tab** (owner only): see above.
- Tabs are a shared component (`components/Tabs.tsx`), also used by Library.

## Not done
- No user search or directory: profiles are found by link.
- No following, comments or activity feed.
- No moderation of names or pictures. Before a public deployment: a report path and a review of what an open upload means (the licensing review already lists covers).
