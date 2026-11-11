# 0024: Account deletion, sign-in limits, anonymous-user cleanup

Status: accepted (2026-11-07, owner request, before M9).

## Deleting an account
- **Where:** Profile Settings, under Delete Account. The page explains what goes, then asks for the password.
- **Route:** `DELETE /api/account` with `{password}`, which returns 204. It deletes the user row, and the database cascades to sessions, ratings, lists, dismissals, chats, recommendation impressions and Ask usage. Feedback messages keep their text, but `user_id` becomes NULL. The profile picture file is removed.
- **Responses:** a wrong password returns 403, not 401, because the browser treats 401 as "session forgotten" and would start a new session. Anonymous users get 403: their library only lives in their browser. Wrong passwords count toward the sign-in limits, so this route can't be used to guess a password.
- **Afterwards:** the browser drops its token, starts a new empty library, goes to Discover and shows a toast. Every other browser signed in to the account gets 401, then starts afresh.

## Sign-in limits
- **Limits:** 5 failed password checks per email, or 20 per device (network address), within 15 minutes. After that, `POST /api/account/login` returns 429 "Too many attempts. Wait 15 minutes, then try again." This happens before the password is checked, so the right password waits too.
- **Reset:** a successful sign-in clears that email's count.
- **Storage:** failures are rows in `login_failures` (migration 0012). Emails and addresses are stored as keyed hashes (`app/limits.py`, HMAC with `INROTATION_SECRET`), and rows older than the window are deleted as new ones arrive. The failure is committed even though the request ends in an error.
- **Why per email and per device:** per email stops guessing one person's password from many addresses. Per device stops trying many emails from one address. A shared address (an office) shares the 20.
- **Not limited:** sign-up. It only turns the caller's own anonymous user into an account.

## Anonymous-user cleanup
- **Command:** `python -m app.cleanup` from `backend/`, with `--dry-run`, `--empty-days` (7) and `--idle-days` (365). It's meant to run once a day (cron or a scheduled container in M9).
- **What it deletes:** anonymous users who are empty and unseen for 7 days, and any anonymous user unseen for 365 days. Accounts are never touched.
- **Empty** means no ratings, list entries, custom lists, dismissals or chats. Recommendation impressions don't count.
- **Seen** is `users.last_seen_at` (migration 0012, existing rows start at `created_at`). It's refreshed by any request with the user's session, at most once a day.
- **Why 365 days for libraries:** an anonymous library lives only in one browser's storage. After a year unseen it's almost certainly unreachable. These numbers are the owner's to change.

## Revision (2026-11-10): limits on new sessions and accounts
With the password gone (ADR 0025), a script could fill the database. Each device (network address, keyed hash as before) may start **30 anonymous sessions an hour** and create **5 accounts a day** (`auth.LIMITS`, `auth.allow`, table `rate_events`, migration 0013). A refused request gets 429 with a plain message, and the site shows it in place of the connection notice. A sign-up refused for bad input doesn't count, because the request rolls back. The nightly cleanup now also deletes expired rows from `login_failures`, `rate_events` and `chat_usage` (`cleanup.prune_limits`), so the keyed hashes go within two days even without new traffic, as the Privacy page says. Checked through Caddy in local Docker: the 31st session in an hour was refused.
