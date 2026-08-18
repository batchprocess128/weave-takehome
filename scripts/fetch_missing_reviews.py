#!/usr/bin/env python3
"""Fetch reviewed-by lists for staff logins missing from reviews.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Reuse the GitHub client and staff rule from fetch/analyze.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import affiliated, load  # noqa: E402
from fetch import END, RAW, REPO, START, GitHub, slim_issue, token  # noqa: E402


def main() -> int:
    users = load("users.json")
    members = set(load("members.json")) if (RAW / "members.json").exists() else set()
    reviews_path = RAW / "reviews.json"
    reviews = json.loads(reviews_path.read_text()) if reviews_path.exists() else {}
    staff = [u["login"] for u in users.values() if affiliated(u, members)]
    missing = [login for login in staff if login not in reviews]
    print(f"staff={len(staff)} already={len(reviews)} missing={len(missing)}", flush=True)
    if not missing:
        return 0
    gh = GitHub(token())

    def month_end(d):
        if d.month == 12:
            nxt = d.replace(year=d.year + 1, month=1, day=1)
        else:
            nxt = d.replace(month=d.month + 1, day=1)
        from datetime import timedelta
        return min(nxt - timedelta(days=1), END)

    def reviewed(login: str) -> list[dict]:
        query = (
            f"repo:{REPO} is:pr is:merged reviewed-by:{login} "
            f"merged:{START.isoformat()}..{END.isoformat()}"
        )
        try:
            items = gh.search_all(query)
        except RuntimeError:
            items = []
            cur = START
            while cur <= END:
                nxt = month_end(cur)
                q = (
                    f"repo:{REPO} is:pr is:merged reviewed-by:{login} "
                    f"merged:{cur.isoformat()}..{nxt.isoformat()}"
                )
                items.extend(gh.search_all(q))
                from datetime import timedelta
                cur = nxt + timedelta(days=1)
        by_num = {it["number"]: slim_issue(it) for it in items if it.get("number")}
        return list(by_num.values())

    for i, login in enumerate(missing, 1):
        reviews[login] = reviewed(login)
        reviews_path.write_text(json.dumps(reviews))
        print(f"  [{i}/{len(missing)}] {login}: {len(reviews[login])}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
