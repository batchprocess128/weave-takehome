#!/usr/bin/env python3
"""Load data/raw/*.json into local Postgres.

The raw files are GitHub search dumps. This script is the ETL step: flatten
nested user objects, explode labels into child tables, and turn reviews.json
(reviewer → list of full PR copies) into a many-to-many of (reviewer, pr).

Affiliation flags reuse scripts/analyze.py so SQL and the dashboard agree
on who is PostHog-affiliated.

    docker compose up -d
    uv sync
    uv run python scripts/load_db.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SCHEMA = ROOT / "db" / "schema.sql"
DEFAULT_URL = "postgresql://weave:weave@localhost:5432/weave"

# Allow `python3 scripts/load_db.py` from the repo root.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze import affiliated  # noqa: E402


def load_json(name: str):
    path = RAW / name
    if not path.exists():
        return None
    return json.loads(path.read_text())


def clean_text(value: object) -> str:
    """Postgres rejects NUL bytes in text columns."""
    return (value or "").replace("\x00", "") if isinstance(value, str) else ""


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def item_row(item: dict) -> tuple:
    user = item.get("user") or {}
    return (
        item.get("number"),
        clean_text(item.get("title")) or "",
        clean_text(item.get("body")),
        item.get("state"),
        item.get("comments") or 0,
        parse_ts(item.get("created_at")),
        parse_ts(item.get("closed_at")),
        parse_ts(item.get("updated_at")),
        item.get("html_url") or "",
        user.get("login"),
        user.get("type"),
    )


def label_rows(number: int, item: dict) -> list[tuple]:
    seen: set[str] = set()
    rows = []
    for lab in item.get("labels") or []:
        if not lab or lab in seen:
            continue
        seen.add(lab)
        rows.append((number, lab))
    return rows


def review_pairs(reviews: dict) -> list[tuple[str, int]]:
    pairs: list[tuple[str, int]] = []
    for login, items in reviews.items():
        seen: set[int] = set()
        for item in items or []:
            number = item.get("number")
            if number is None or number in seen:
                continue
            seen.add(number)
            pairs.append((login, number))
    return pairs


def extra_prs_from_reviews(prs: list[dict], reviews: dict) -> list[dict]:
    """reviews.json can contain a PR the merged-PR search missed (one today)."""
    have = {p["number"] for p in prs if p.get("number") is not None}
    extra = []
    for items in reviews.values():
        for item in items or []:
            number = item.get("number")
            if number is None or number in have:
                continue
            have.add(number)
            extra.append(item)
    return extra


ITEM_SQL = """
INSERT INTO {table} (
    number, title, body, state, comments,
    created_at, closed_at, updated_at, html_url, author_login, author_type
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def main() -> int:
    try:
        import psycopg
    except ImportError:
        print(
            "Install project deps first:  uv sync",
            file=sys.stderr,
        )
        return 1

    if not (RAW / "prs.json").exists():
        print("Run scripts/fetch.py first so data/raw/ is populated.", file=sys.stderr)
        return 1

    meta = load_json("meta.json") or {}
    prs = load_json("prs.json") or []
    issues = load_json("issues.json") or []
    users = load_json("users.json") or {}
    reviews = load_json("reviews.json") or {}
    members = set(load_json("members.json") or meta.get("public_members") or [])

    extras = extra_prs_from_reviews(prs, reviews)
    if extras:
        print(f"adding {len(extras)} PR(s) present in reviews.json but not prs.json")
        prs = prs + extras

    url = os.environ.get("DATABASE_URL") or DEFAULT_URL
    print(f"loading {url}")

    with psycopg.connect(url, autocommit=False) as conn:
        conn.execute(SCHEMA.read_text())

        conn.execute(
            """
            INSERT INTO fetch_meta (
                repo, window_start, window_end, fetched_at,
                pr_count, issue_count, user_count, staff_count
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                meta.get("repo") or "PostHog/posthog",
                meta.get("start") or "2026-05-20",
                meta.get("end") or "2026-08-18",
                parse_ts(meta.get("fetched_at")),
                len(prs),
                len(issues),
                len(users),
                sum(1 for u in users.values() if affiliated(u, members)),
            ),
        )

        member_rows = [(login,) for login in sorted(members) if login]
        if member_rows:
            conn.cursor().executemany(
                "INSERT INTO org_members (login) VALUES (%s)",
                member_rows,
            )

        user_rows = []
        for login, u in users.items():
            user_rows.append(
                (
                    u.get("login") or login,
                    u.get("name"),
                    u.get("company"),
                    u.get("type"),
                    clean_text(u.get("bio")),
                    u.get("avatar_url"),
                    u.get("html_url"),
                    u.get("merged_pr_count") or 0,
                    login in members,
                    affiliated(u, members),
                )
            )
        conn.cursor().executemany(
            """
            INSERT INTO users (
                login, name, company, type, bio, avatar_url, html_url,
                merged_pr_count, is_public_member, is_affiliated
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            user_rows,
        )

        conn.cursor().executemany(ITEM_SQL.format(table="prs"), [item_row(p) for p in prs])
        conn.cursor().executemany(ITEM_SQL.format(table="issues"), [item_row(i) for i in issues])

        pr_label_rows = []
        for p in prs:
            if p.get("number") is not None:
                pr_label_rows.extend(label_rows(p["number"], p))
        if pr_label_rows:
            conn.cursor().executemany(
                "INSERT INTO pr_labels (pr_number, label) VALUES (%s, %s)",
                pr_label_rows,
            )

        issue_label_rows = []
        for i in issues:
            if i.get("number") is not None:
                issue_label_rows.extend(label_rows(i["number"], i))
        if issue_label_rows:
            conn.cursor().executemany(
                "INSERT INTO issue_labels (issue_number, label) VALUES (%s, %s)",
                issue_label_rows,
            )

        pairs = review_pairs(reviews)
        if pairs:
            conn.cursor().executemany(
                "INSERT INTO reviews (reviewer_login, pr_number) VALUES (%s, %s)",
                pairs,
            )

        conn.commit()

    print(
        f"loaded {len(prs)} prs, {len(issues)} issues, {len(user_rows)} users, "
        f"{len(pairs)} review pairs, {len(pr_label_rows)} pr labels"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
