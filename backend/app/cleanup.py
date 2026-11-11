"""Delete old anonymous users (owner request 2026-11-07), and the expired rows behind the rate limits (the
Privacy page says those keyed hashes go within two days). Run from backend/, for example once a day:

    python -m app.cleanup --dry-run        # counts only
    python -m app.cleanup                  # empty after 7 days unseen, with saved albums after 365

Every visitor gets an anonymous user on their first save or library load, and most never come back. Accounts
are never touched. "Empty" means nothing the person made: no ratings, list entries, custom lists, dismissals or
chats. An anonymous library with saved albums only lives in one browser's storage, so after a year unseen it's
almost certainly unreachable. "Seen" is users.last_seen_at, refreshed at most once a day per user.
"""
import argparse
from datetime import timedelta

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.orm import Session as Db

from .auth import FAILURE_WINDOW
from .schema import CUSTOM, ChatUsage, Conversation, Dismissal, List, ListItem, LoginFailure, RateEvent, Rating, User, now

EMPTY_DAYS = 7
IDLE_DAYS = 365
BATCH = 1000


def _anonymous_unseen(days: int):
    last_seen = func.coalesce(User.last_seen_at, User.created_at)
    return select(User.id).where(User.email.is_(None), last_seen < now() - timedelta(days=days))


def _has_something():
    """True for users who made anything worth keeping."""
    return or_(
        exists().where(Rating.user_id == User.id),
        exists().where(Dismissal.user_id == User.id),
        exists().where(Conversation.user_id == User.id),
        exists().where(List.user_id == User.id, List.kind == CUSTOM),
        exists(select(ListItem.list_id).join(List, ListItem.list_id == List.id).where(List.user_id == User.id)),
    )


def stale_users(db: Db, empty_days: int = EMPTY_DAYS, idle_days: int = IDLE_DAYS) -> list[str]:
    """Ids of anonymous users to delete: empty and unseen for empty_days, or unseen for idle_days whatever they hold."""
    empty = _anonymous_unseen(empty_days).where(~_has_something())
    idle = _anonymous_unseen(idle_days)
    return list(db.scalars(empty.union(idle)))


def clean(db: Db, empty_days: int = EMPTY_DAYS, idle_days: int = IDLE_DAYS, dry_run: bool = False) -> int:
    """Delete stale anonymous users in batches (cascading to their sessions, lists and the rest). Returns how many."""
    ids = stale_users(db, empty_days, idle_days)
    if not dry_run:
        for i in range(0, len(ids), BATCH):
            db.execute(delete(User).where(User.id.in_(ids[i:i + BATCH]), User.email.is_(None)))
            db.commit()
    return len(ids)


def prune_limits(db: Db) -> int:
    """Delete rate-limit rows past any window: sign-in failures after FAILURE_WINDOW, new-session and sign-up
    counts after a day, Ask's daily counts before yesterday. These only hold keyed hashes, but none should
    outlive its use. The requests themselves prune too, but only when new rows arrive."""
    at = now()
    n = db.execute(delete(LoginFailure).where(LoginFailure.at < at - FAILURE_WINDOW)).rowcount
    n += db.execute(delete(RateEvent).where(RateEvent.at < at - timedelta(days=1))).rowcount
    n += db.execute(delete(ChatUsage).where(ChatUsage.day < (at - timedelta(days=1)).date())).rowcount
    db.commit()
    return n


def main() -> None:
    from pathlib import Path

    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")      # backend/.env, as the API does
    from sqlalchemy.orm import Session

    from .db import check_schema, get_engine

    p = argparse.ArgumentParser(description="Delete old anonymous users. Accounts are never touched.")
    p.add_argument("--empty-days", type=int, default=EMPTY_DAYS, help="delete empty ones unseen this long (default 7)")
    p.add_argument("--idle-days", type=int, default=IDLE_DAYS, help="delete any unseen this long (default 365)")
    p.add_argument("--dry-run", action="store_true", help="only count")
    args = p.parse_args()
    if args.empty_days < 1 or args.idle_days < args.empty_days:
        p.error("use --empty-days of at least 1 and --idle-days of at least --empty-days")
    check_schema()
    with Session(get_engine()) as db:
        total = db.scalar(select(func.count()).select_from(User).where(User.email.is_(None)))
        n = clean(db, args.empty_days, args.idle_days, args.dry_run)
        pruned = 0 if args.dry_run else prune_limits(db)
    verb = "Would delete" if args.dry_run else "Deleted"
    print(f"{verb} {n:,} of {total:,} anonymous users (empty and unseen {args.empty_days}+ days, "
          f"or unseen {args.idle_days}+ days). Deleted {pruned:,} expired rate-limit rows.")


if __name__ == "__main__":
    main()
