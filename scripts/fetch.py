#!/usr/bin/env python3
"""Fetch 90+ days of PostHog/posthog GitHub data into data/raw/."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = "PostHog/posthog"
# Assignment requires at least the last 90 days. Inclusive window ending today.
END = date(2026, 8, 18)
START = END - timedelta(days=90)  # 2026-05-20
WINDOW_DAYS = 4
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

BOT_HINTS = (
    "bot",
    "dependabot",
    "renovate",
    "greptile",
    "changeset",
    "github-actions",
    "imgbot",
    "codecov",
    "cursor",
    "copilot",
    "semantic-release",
    "vercel",
    "netlify",
    "snyk",
)


def token() -> str:
    env = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if env:
        return env.strip()
    return subprocess.check_output(["gh", "auth", "token"], text=True).strip()


class GitHub:
    def __init__(self, tok: str) -> None:
        self.tok = tok
        self.search_remaining = 30
        self.search_reset = 0

    def _request(self, url: str) -> dict:
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.tok}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "weave-posthog-impact",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
                self.search_remaining = int(resp.headers.get("X-RateLimit-Remaining", self.search_remaining))
                self.search_reset = int(resp.headers.get("X-RateLimit-Reset", self.search_reset) or 0)
                return body
        except urllib.error.HTTPError as e:
            retry_after = e.headers.get("Retry-After")
            if e.code in (403, 429):
                wait = int(retry_after) if retry_after else 60
                print(f"  rate limited ({e.code}), sleeping {wait}s", flush=True)
                time.sleep(wait + 1)
                return self._request(url)
            raise

    def wait_search(self) -> None:
        if self.search_remaining <= 2 and self.search_reset:
            wait = max(0, self.search_reset - int(time.time())) + 1
            if wait > 0:
                print(f"  search budget low ({self.search_remaining}), sleeping {wait}s", flush=True)
                time.sleep(wait)

    def search_all(self, query: str) -> list[dict]:
        """Paginate a search query. Splits the caller should keep results <= 1000."""
        items: list[dict] = []
        page = 1
        while True:
            self.wait_search()
            q = urllib.parse.quote(query)
            url = f"https://api.github.com/search/issues?q={q}&per_page=100&page={page}"
            data = self._request(url)
            batch = data.get("items") or []
            total = data.get("total_count", 0)
            if page == 1:
                print(f"    {query!r} → {total} hits", flush=True)
                if total > 1000:
                    raise RuntimeError(f"window exceeds 1000 results ({total}): {query}")
            items.extend(batch)
            if len(batch) < 100 or len(items) >= total:
                break
            page += 1
            time.sleep(0.3)
        return items

    def user(self, login: str) -> dict:
        url = f"https://api.github.com/users/{urllib.parse.quote(login)}"
        return self._request(url)


def date_windows(start: date, end: date, days: int) -> list[tuple[date, date]]:
    windows = []
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=days - 1), end)
        windows.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return windows


def slim_issue(item: dict) -> dict:
    user = item.get("user") or {}
    labels = []
    for lab in item.get("labels") or []:
        if isinstance(lab, dict):
            labels.append(lab.get("name") or "")
        else:
            labels.append(str(lab))
    return {
        "number": item.get("number"),
        "title": item.get("title") or "",
        "body": item.get("body") or "",
        "html_url": item.get("html_url") or "",
        "state": item.get("state"),
        "comments": item.get("comments") or 0,
        "created_at": item.get("created_at"),
        "closed_at": item.get("closed_at"),
        "updated_at": item.get("updated_at"),
        "user": {
            "login": user.get("login"),
            "type": user.get("type"),
            "avatar_url": user.get("avatar_url"),
        },
        "labels": [l for l in labels if l],
        "pull_request": bool(item.get("pull_request")),
    }


def is_bot_login(login: str | None) -> bool:
    if not login:
        return True
    low = login.lower()
    return any(h in low for h in BOT_HINTS)


def fetch_search_range(gh: GitHub, kind: str, field: str) -> list[dict]:
    """kind is 'pr' or 'issue'. field is 'merged', 'closed', or 'created'."""
    extra = "is:merged" if kind == "pr" else ""
    collected: dict[int, dict] = {}
    for a, b in date_windows(START, END, WINDOW_DAYS):
        query = f"repo:{REPO} is:{kind} {extra} {field}:{a.isoformat()}..{b.isoformat()}".strip()
        try:
            items = gh.search_all(query)
        except RuntimeError:
            # Split a too-large window into single days.
            print(f"  splitting {a}..{b}", flush=True)
            items = []
            day = a
            while day <= b:
                q = f"repo:{REPO} is:{kind} {extra} {field}:{day.isoformat()}..{day.isoformat()}".strip()
                items.extend(gh.search_all(q))
                day += timedelta(days=1)
        for it in items:
            slim = slim_issue(it)
            if slim["number"] is not None:
                collected[slim["number"]] = slim
    return list(collected.values())


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    gh = GitHub(token())
    meta = {
        "repo": REPO,
        "start": START.isoformat(),
        "end": END.isoformat(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    print(f"Fetching {REPO} {START} → {END}", flush=True)

    prs_path = RAW / "prs.json"
    issues_path = RAW / "issues.json"
    if prs_path.exists():
        prs = json.loads(prs_path.read_text())
        print(f"== merged PRs == reused {len(prs)} from disk", flush=True)
    else:
        print("== merged PRs ==", flush=True)
        prs = fetch_search_range(gh, "pr", "merged")
        prs_path.write_text(json.dumps(prs, indent=None))
        print(f"  saved {len(prs)} PRs", flush=True)

    if issues_path.exists():
        issues = json.loads(issues_path.read_text())
        print(f"== issues == reused {len(issues)} from disk", flush=True)
    else:
        print("== issues closed ==", flush=True)
        issues_closed = fetch_search_range(gh, "issue", "closed")
        print("== issues created ==", flush=True)
        issues_created = fetch_search_range(gh, "issue", "created")
        issues_by_num: dict[int, dict] = {}
        for it in issues_closed + issues_created:
            issues_by_num[it["number"]] = it
        issues = list(issues_by_num.values())
        issues_path.write_text(json.dumps(issues))
        print(f"  saved {len(issues)} issues", flush=True)

    # Affiliation lookup for authors with enough signal to matter.
    counts: dict[str, int] = {}
    for pr in prs:
        login = (pr.get("user") or {}).get("login")
        if not login or is_bot_login(login) or (pr.get("user") or {}).get("type") == "Bot":
            continue
        counts[login] = counts.get(login, 0) + 1

    print("== org public members (union with company match) ==", flush=True)
    try:
        members_raw = gh._request("https://api.github.com/orgs/PostHog/public_members?per_page=100")
        member_logins = [m.get("login") for m in members_raw if m.get("login")]
    except Exception as e:
        print(f"  public members failed: {e}", flush=True)
        member_logins = []
    print(f"  {len(member_logins)} public members", flush=True)

    candidates = sorted(set(counts) | set(member_logins), key=lambda u: -counts.get(u, 0))
    print(f"== profiles for {len(candidates)} authors/members ==", flush=True)
    users: dict[str, dict] = {}
    for i, login in enumerate(candidates, 1):
        try:
            u = gh.user(login)
        except Exception as e:
            print(f"  skip {login}: {e}", flush=True)
            continue
        users[login] = {
            "login": u.get("login"),
            "name": u.get("name"),
            "company": u.get("company"),
            "type": u.get("type"),
            "avatar_url": u.get("avatar_url"),
            "html_url": u.get("html_url"),
            "bio": u.get("bio"),
            "merged_pr_count": counts.get(login, 0),
        }
        if i % 25 == 0:
            print(f"  {i}/{len(candidates)}", flush=True)
        time.sleep(0.05)
    users_path = RAW / "users.json"
    users_path.write_text(json.dumps(users))
    print(f"  saved {len(users)} users", flush=True)

    def is_posthog(u: dict) -> bool:
        company = (u.get("company") or "").lower().replace("@", "")
        return "posthog" in company

    member_set = set(member_logins)
    staff = [
        u
        for u in users.values()
        if u.get("type") != "Bot"
        and (is_posthog(u) or u.get("login") in member_set)
    ]
    staff_logins = [u["login"] for u in staff]
    print(f"== PostHog-affiliated engineers: {len(staff_logins)} ==", flush=True)

    print("== reviews given (staff only) ==", flush=True)
    reviews_path = RAW / "reviews.json"
    reviews: dict[str, list[dict]] = json.loads(reviews_path.read_text()) if reviews_path.exists() else {}
    for i, login in enumerate(staff_logins, 1):
        if login in reviews:
            print(f"  [{i}/{len(staff_logins)}] {login}: reused {len(reviews[login])}", flush=True)
            continue
        query = f"repo:{REPO} is:pr is:merged reviewed-by:{login} merged:{START.isoformat()}..{END.isoformat()}"
        try:
            items = gh.search_all(query)
        except RuntimeError:
            # Too many reviews — split by month.
            items = []
            cur = START
            while cur <= END:
                nxt = min(date(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1) - timedelta(days=1), END)
                q = f"repo:{REPO} is:pr is:merged reviewed-by:{login} merged:{cur.isoformat()}..{nxt.isoformat()}"
                try:
                    items.extend(gh.search_all(q))
                except RuntimeError:
                    day = cur
                    while day <= nxt:
                        qd = f"repo:{REPO} is:pr is:merged reviewed-by:{login} merged:{day.isoformat()}..{day.isoformat()}"
                        items.extend(gh.search_all(qd))
                        day += timedelta(days=1)
                cur = nxt + timedelta(days=1)
        # Dedupe
        by_num = {it["number"]: slim_issue(it) for it in items if it.get("number")}
        reviews[login] = list(by_num.values())
        reviews_path.write_text(json.dumps(reviews))
        print(f"  [{i}/{len(staff_logins)}] {login}: {len(reviews[login])} reviewed PRs", flush=True)

    (RAW / "reviews.json").write_text(json.dumps(reviews))
    meta["pr_count"] = len(prs)
    meta["issue_count"] = len(issues)
    meta["user_count"] = len(users)
    meta["staff_count"] = len(staff_logins)
    meta["staff"] = staff_logins
    meta["public_members"] = member_logins
    (RAW / "meta.json").write_text(json.dumps(meta, indent=2))
    print("done.", json.dumps(meta, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
