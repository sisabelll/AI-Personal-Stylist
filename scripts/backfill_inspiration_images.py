"""
One-off repair for `inspiration_items` rows written before image mirroring.

Two things are wrong with the existing data:

  * Duplicates. dedupe_key used to hash scheme+host+path, and Instagram serves
    the same photo from a rotating edge host, so one photo accumulated up to ten
    rows across pipeline runs.
  * Dead images. The stored Instagram URLs are signed with an `oe` expiry a
    couple of weeks out. Every one of them now returns 403, so the board fetches
    them, gets nothing, and drops the card.

This script recomputes the identity, collapses each photo down to a single row
(preferring the one carrying user feedback so saves are never lost), mirrors the
image into Supabase Storage, and rewrites image_url to the permanent URL.

Usage:
    PYTHONPATH=. python scripts/backfill_inspiration_images.py                 # dry run, all users
    PYTHONPATH=. python scripts/backfill_inspiration_images.py --apply
    PYTHONPATH=. python scripts/backfill_inspiration_images.py --user <uuid> --apply
    PYTHONPATH=. python scripts/backfill_inspiration_images.py --apply --prune-dead
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

import core.config  # noqa: F401  — loads .env before the Supabase client is built
from services.storage import StorageService
from services.image_identity import image_dedupe_key
from services.image_mirror import mirror_image, download_image, BUCKET_NAME, ensure_bucket

# A row the user has acted on is worth more than an untouched one.
_FEEDBACK_RANK = {"save": 3, "like": 2, None: 1, "": 1, "dislike": 0, "hide": 0}


def _row_rank(row: Dict[str, Any]) -> tuple:
    """Pick the survivor: user feedback first, then richer tags, then score."""
    return (
        _FEEDBACK_RANK.get(row.get("feedback"), 1),
        len(row.get("tags") or []),
        float(row.get("score") or 0.0),
    )


def load_rows(sb, user_id: str = None) -> List[Dict[str, Any]]:
    q = sb.table("inspiration_items").select("*")
    if user_id:
        q = q.eq("user_id", user_id)
    return q.limit(10000).execute().data or []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", help="restrict to one user_id")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--prune-dead", action="store_true",
                    help="delete rows whose source image can no longer be fetched")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    storage = StorageService()
    sb = storage.supabase
    admin = getattr(storage, "db_admin", None) or sb

    rows = load_rows(sb, args.user)
    if not rows:
        print("No inspiration_items rows found.")
        return 0

    by_user = defaultdict(list)
    for r in rows:
        by_user[r["user_id"]].append(r)

    print(f"{'APPLY' if args.apply else 'DRY RUN'} · {len(rows)} rows across {len(by_user)} user(s)")
    if args.apply and not ensure_bucket(admin):
        print("ERROR: could not create or reach the Supabase Storage bucket "
              f"{BUCKET_NAME!r}. Check SUPABASE_SERVICE_KEY.")
        return 1
    print()

    totals = Counter()

    for user_id, user_rows in by_user.items():
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in user_rows:
            key = image_dedupe_key(r.get("image_url") or "")
            if not key:
                totals["no_url"] += 1
                continue
            groups[key].append(r)

        survivors, losers = [], []
        for key, members in groups.items():
            members.sort(key=_row_rank, reverse=True)
            survivor = members[0]
            survivor["_new_dedupe_key"] = key
            # Carry the strongest feedback in the group onto the survivor so a
            # save recorded on a duplicate row isn't thrown away with it.
            best_feedback = max(members, key=_row_rank).get("feedback")
            if best_feedback and not survivor.get("feedback"):
                survivor["feedback"] = best_feedback
            survivors.append(survivor)
            losers.extend(members[1:])

        print(f"user {user_id}")
        print(f"  {len(user_rows)} rows -> {len(survivors)} unique photos "
              f"({len(losers)} duplicate rows to delete)")

        # Mirror survivors in parallel.
        def _mirror(row):
            url = row.get("image_url") or ""
            if f"/{BUCKET_NAME}/" in url:
                return ("already", row, url)
            if not args.apply:
                return ("would" if download_image(url) else "dead", row, None)
            permanent = mirror_image(admin, user_id, url)
            return ("ok" if permanent else "dead", row, permanent)

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            results = list(ex.map(_mirror, survivors))

        outcome = Counter(status for status, _, _ in results)
        print(f"  mirror: {dict(outcome)}")
        totals.update(outcome)
        totals["duplicates_removed"] += len(losers)

        if not args.apply:
            print()
            continue

        # 1. Delete duplicate rows.
        for loser in losers:
            try:
                sb.table("inspiration_items").delete().eq("id", loser["id"]).execute()
            except Exception as e:
                print(f"    delete {loser['id']} failed: {e}")

        # 2. Rewrite survivors to the permanent URL + corrected dedupe_key.
        dead = []
        for status, row, permanent in results:
            if status == "dead":
                dead.append(row)
                continue
            payload = {"dedupe_key": row["_new_dedupe_key"]}
            if permanent and status == "ok":
                payload["image_url"] = permanent
            if row.get("feedback"):
                payload["feedback"] = row["feedback"]
            try:
                sb.table("inspiration_items").update(payload).eq("id", row["id"]).execute()
            except Exception as e:
                print(f"    update {row['id']} failed: {e}")

        # 3. Optionally drop rows whose image is gone for good.
        if dead:
            if args.prune_dead:
                for row in dead:
                    try:
                        sb.table("inspiration_items").delete().eq("id", row["id"]).execute()
                    except Exception as e:
                        print(f"    prune {row['id']} failed: {e}")
                print(f"  pruned {len(dead)} rows with unreachable images")
            else:
                print(f"  {len(dead)} rows have unreachable images "
                      f"(re-run with --prune-dead to delete them)")
        print()

    print("=" * 60)
    print("TOTALS:", dict(totals))
    if not args.apply:
        print("\nDry run — nothing was written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
