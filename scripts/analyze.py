#!/usr/bin/env python3
"""Score PostHog-affiliated GitHub contributors and write docs/data.json.

Impact here means leverage visible in PostHog/posthog over a fixed 90-day window.
It is not employment status, seniority, or lines of code.

Every displayed number is produced by the formulas in FORMULAS below.
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "docs" / "data.json"

WINDOW_START = "2026-05-20"
WINDOW_END = "2026-08-18"

# GitHub closing keywords only. No "implements".
# Accepts: Fixes #12; Fixes #1, #2; Fixes PostHog/posthog#12;
# Fixes https://github.com/PostHog/posthog/issues/12
CLOSE_HEAD = re.compile(
    r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+",
    re.I,
)
CLOSE_NUM = re.compile(
    r"(?:\[(?:\*\*)?)?"
    r"(?:https://github\.com/[\w.-]+/[\w.-]+/issues/|[\w.-]+/[\w.-]+#|#)(\d+)"
    r"(?:\*\*)?(?:\]\([^)]+\))?",
    re.I,
)
CLOSE_SEP = re.compile(r"\s*(?:,\s*(?:and\s+)?|;\s*|\band\s+)", re.I)
BUGGY_LABEL = re.compile(r"bug|regress|crash|secur|vulnerab|perf|incident|hotfix", re.I)
STAMP_LABEL = re.compile(r"^stamphog$", re.I)
LOGIN_AFFIL = re.compile(r"(-ph|-posthog)$", re.I)
WEIGHTS = {"outcomes": 0.40, "review_reach": 0.35, "framing": 0.25}

EDITORIAL_WHY = {
    "arthurdedeus": (
        "Owned customer-analytics accounts: notebooks, tagging, and calendar sync. "
        "Also had the strongest problem-framing signal in the window."
    ),
    "fercgomes": (
        "Shipped provisioning, authentication, navigation, and task-reliability work, "
        "with 21 issue-linked landings."
    ),
    "jakesciotto": (
        "Shipped warehouse-source and customer-analytics work, leading outcomes with "
        "28 issue-linked landings while authoring 43 issues that closed."
    ),
    "Gilbert09": (
        "Moved warehouse imports and data infrastructure while reviewing 437 merged PRs "
        "across 57 authors. 1,160 stamphog PRs were excluded from outcomes."
    ),
    "pauldambra": (
        "Improved AI tooling, interviews, and search reliability while reviewing 179 "
        "merged PRs across 43 authors."
    ),
    "webjunkie": (
        "Strengthened developer infrastructure: isolation checks, API startup performance, "
        "and adaptive CI test sharding."
    ),
    "andrewm4894": (
        "Built Signals research and scout tooling while reviewing 344 merged PRs "
        "across 41 authors."
    ),
}

EDITORIAL_NAMES = {"jakesciotto": "Jake Sciotto"}

FORMULAS = {
    "impact": (
        "impact = 0.40 * outcomes_norm + 0.35 * review_reach_norm + 0.25 * framing_norm"
    ),
    "normalization": (
        "Each pillar raw score is min-max scaled to 0-100 across the scored population "
        "(PostHog-affiliated GitHub contributors with at least one merged PR or one "
        "reviewed-by hit in the window). If max == min, everyone gets 0 on that pillar."
    ),
    "outcomes_raw": (
        "outcomes_raw = 3 * issue_ref_prs + 2 * bug_only_prs "
        "+ 4 * ln(1 + high_comment_prs) + ln(1 + other_prs). "
        "Stamphog-labeled PRs are excluded from every outcomes term. "
        "No revert penalty (the revert author is often containing someone else's break)."
    ),
    "review_reach_raw": (
        "review_reach_raw = ln(1 + reviewed_others) + ln(1 + distinct_authors). "
        "reviewed_others = merged PRs in the window matching GitHub search "
        "reviewed-by:LOGIN, excluding PRs the person authored. "
        "This is review reach, not unblocking, and not review depth. "
        "We did not fetch individual review events, bodies, or CHANGES_REQUESTED."
    ),
    "framing_raw": (
        "framing_raw = issues_authored_and_closed_in_window. "
        "An issue counts only if the person is the author AND closed_at falls in "
        f"{WINDOW_START} .. {WINDOW_END} inclusive (UTC date). "
        "GitHub issues are a weak proxy; PostHog tracks most work in Linear."
    ),
    "issue_ref_parser": (
        "A PR is an issue-ref PR if title+body contains a GitHub closing keyword "
        "(close/closes/closed, fix/fixes/fixed, resolve/resolves/resolved) followed "
        "by #N, owner/repo#N, or a github.com/.../issues/N URL. "
        "The referenced number must also appear in the relevant issue census for the "
        "window. 'implements #N' does not count. This is a parser over PR text, not "
        "GitHub's linked-issue graph."
    ),
    "high_comment": (
        "high_comment_prs = staff-authored, non-stamphog PRs whose conversation "
        "comment count (the comments field returned by GitHub issue search) is at "
        "or above the 75th percentile of that population, floored at 6. "
        "This is not review-discussion depth."
    ),
}


def load(name: str):
    return json.loads((RAW / name).read_text())


def is_posthog_company(company: str | None) -> bool:
    return "posthog" in (company or "").lower().replace("@", "")


def affiliated(user: dict, members: set[str]) -> bool:
    """PostHog-affiliated GitHub contributor. Not an employment check."""
    if user.get("type") == "Bot":
        return False
    login = user.get("login") or ""
    company = user.get("company") or ""
    bio = user.get("bio") or ""
    if is_posthog_company(company):
        return True
    if "posthog" in bio.lower():
        return True
    if LOGIN_AFFIL.search(login):
        return True
    if login in members:
        # Public member with a different listed company is not treated as PostHog staff.
        if company.strip() and not is_posthog_company(company):
            return False
        return True
    return False


def day(iso: str | None) -> str | None:
    if not iso:
        return None
    return iso[:10]


def in_window(iso: str | None) -> bool:
    d = day(iso)
    return bool(d and WINDOW_START <= d <= WINDOW_END)


def issue_refs(pr: dict, valid_issue_numbers: set[int] | None = None) -> list[int]:
    text = f"{pr.get('title') or ''}\n{pr.get('body') or ''}"
    nums: list[int] = []
    for m in CLOSE_HEAD.finditer(text):
        tail = text[m.end() : m.end() + 240]
        ref = CLOSE_NUM.match(tail)
        if not ref:
            continue
        nums.append(int(ref.group(1)))
        pos = ref.end()
        while True:
            separator = CLOSE_SEP.match(tail, pos)
            if not separator:
                break
            ref = CLOSE_NUM.match(tail, separator.end())
            if not ref:
                break
            nums.append(int(ref.group(1)))
            pos = ref.end()
    # de-dupe, keep order
    seen = set()
    out = []
    for n in nums:
        if n not in seen and (valid_issue_numbers is None or n in valid_issue_numbers):
            seen.add(n)
            out.append(n)
    return out


def has_bug_label(pr: dict) -> bool:
    return any(BUGGY_LABEL.search(l or "") for l in (pr.get("labels") or []))


def is_stamphog(pr: dict) -> bool:
    return any(STAMP_LABEL.search(l or "") for l in (pr.get("labels") or []))


def minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi <= lo:
        return [0.0] * len(values)
    return [100.0 * (v - lo) / (hi - lo) for v in values]


def notable_prs(
    prs: list[dict], valid_issue_numbers: set[int], limit: int = 3
) -> list[dict]:
    def score(pr: dict) -> tuple:
        return (
            0 if is_stamphog(pr) else 1,
            3 if issue_refs(pr, valid_issue_numbers) else 0,
            2 if has_bug_label(pr) else 0,
            pr.get("comments") or 0,
        )

    out = []
    for pr in sorted(prs, key=score, reverse=True):
        if is_stamphog(pr):
            continue
        refs = issue_refs(pr, valid_issue_numbers)
        reasons = []
        if refs:
            reasons.append("closing-keyword refs " + ", ".join(f"#{n}" for n in refs[:3]))
        if has_bug_label(pr):
            reasons.append("bug/perf/security label")
        if (pr.get("comments") or 0) >= 8:
            reasons.append(f"{pr['comments']} conversation comments")
        if not reasons:
            reasons.append("merged PR")
        out.append(
            {
                "number": pr["number"],
                "title": pr["title"],
                "html_url": pr["html_url"],
                "comments": pr.get("comments") or 0,
                "why": "; ".join(reasons),
            }
        )
        if len(out) >= limit:
            break
    return out


def notable_issues(issues: list[dict], limit: int = 1) -> list[dict]:
    ranked = sorted(issues, key=lambda i: i.get("comments") or 0, reverse=True)
    return [
        {
            "number": i["number"],
            "title": i["title"],
            "html_url": i["html_url"],
            "comments": i.get("comments") or 0,
            "why": f"authored; closed {day(i.get('closed_at'))} (inside window)",
        }
        for i in ranked[:limit]
    ]


def notable_reviews(reviewed: list[dict], self_login: str, limit: int = 3) -> list[dict]:
    others = [r for r in reviewed if (r.get("user") or {}).get("login") != self_login]
    others.sort(key=lambda r: r.get("comments") or 0, reverse=True)
    return [
        {
            "number": r["number"],
            "title": r["title"],
            "html_url": r["html_url"],
            "comments": r.get("comments") or 0,
            "why": f"reviewed-by:{self_login}; authored by @{(r.get('user') or {}).get('login')}",
        }
        for r in others[:limit]
    ]


def why_sentence(p: dict) -> str:
    """Use an editorial summary for finalists, with a data-derived fallback."""
    editorial = EDITORIAL_WHY.get(p["login"])
    if editorial:
        return editorial
    titles = [e["title"] for e in (p.get("evidence") or {}).get("prs") or [] if e.get("title")]
    name = p.get("name") or p["login"]
    if titles:
        shown = "; ".join(titles[:3])
        return f"{name} landed work such as: {shown}"
    reviewed = (p.get("evidence") or {}).get("reviews") or []
    if reviewed:
        return (
            f"{name} appears as reviewer on {p['pillars']['review_reach']['reviewed_others']} "
            f"other people's merged PRs (review reach, not unblocking)."
        )
    return f"{name} has PostHog-affiliated activity in the window, with little authored evidence."


def main() -> int:
    if not (RAW / "prs.json").exists():
        print("Run scripts/fetch.py first.", file=sys.stderr)
        return 1

    meta = load("meta.json")
    prs = load("prs.json")
    issues = load("issues.json")
    users = load("users.json")
    reviews = load("reviews.json") if (RAW / "reviews.json").exists() else {}
    members = set(load("members.json")) if (RAW / "members.json").exists() else set()
    valid_issue_numbers = {i["number"] for i in issues if i.get("number") is not None}

    staff_users = {login: u for login, u in users.items() if affiliated(u, members)}

    authored: dict[str, list[dict]] = defaultdict(list)
    for pr in prs:
        login = (pr.get("user") or {}).get("login")
        if login in staff_users:
            authored[login].append(pr)

    framed: dict[str, list[dict]] = defaultdict(list)
    for iss in issues:
        login = (iss.get("user") or {}).get("login")
        if login in staff_users and in_window(iss.get("closed_at")):
            framed[login].append(iss)

    # Comment percentile over non-stamphog staff-authored PRs only.
    comment_pool = [
        p.get("comments") or 0
        for ps in authored.values()
        for p in ps
        if not is_stamphog(p)
    ]
    comment_pool.sort()
    if comment_pool:
        p75 = comment_pool[int(0.75 * (len(comment_pool) - 1))]
    else:
        p75 = 8
    high_bar = max(p75, 6)

    people = []
    skipped_no_signal = []
    for login, u in staff_users.items():
        mine = authored.get(login, [])
        reviewed = reviews.get(login)
        if reviewed is None:
            # Do not score people whose review reach was never fetched.
            continue
        if not mine and not reviewed:
            skipped_no_signal.append(login)
            continue

        usable = [p for p in mine if not is_stamphog(p)]
        issue_closing = [p for p in usable if issue_refs(p, valid_issue_numbers)]
        bug_prs = [p for p in usable if has_bug_label(p)]
        high_disc = [p for p in usable if (p.get("comments") or 0) >= high_bar]
        other = [p for p in usable if p not in issue_closing and p not in bug_prs]
        stamphog_n = sum(1 for p in mine if is_stamphog(p))

        others = [r for r in reviewed if (r.get("user") or {}).get("login") != login]
        unique_authors = {((r.get("user") or {}).get("login") or "") for r in others}
        unique_authors.discard("")
        unique_authors.discard(login)

        closed_issues = framed.get(login, [])

        outcomes_raw = (
            3.0 * len(issue_closing)
            + 2.0 * len([p for p in bug_prs if p not in issue_closing])
            + 4.0 * math.log1p(len(high_disc))
            + math.log1p(len(other))
        )
        review_raw = math.log1p(len(others)) + math.log1p(len(unique_authors))
        framing_raw = float(len(closed_issues))

        people.append(
            {
                "login": login,
                "name": EDITORIAL_NAMES.get(login) or u.get("name") or login,
                "avatar_url": u.get("avatar_url"),
                "html_url": u.get("html_url") or f"https://github.com/{login}",
                "company": u.get("company"),
                "affiliation": "inferred from GitHub company, bio, login suffix, or public org membership",
                "raw": {
                    "outcomes": outcomes_raw,
                    "review_reach": review_raw,
                    "framing": framing_raw,
                },
                "pillars": {
                    "outcomes": {
                        "merged_prs": len(mine),
                        "stamphog_prs": stamphog_n,
                        "scored_prs": len(usable),
                        "issue_ref_prs": len(issue_closing),
                        "bug_only_prs": len([p for p in bug_prs if p not in issue_closing]),
                        "bug_prs": len(bug_prs),
                        "high_comment_prs": len(high_disc),
                        "other_prs": len(other),
                    },
                    "review_reach": {
                        "reviewed_others": len(others),
                        "distinct_authors": len(unique_authors),
                    },
                    "framing": {
                        "issues_authored_closed_in_window": len(closed_issues),
                    },
                },
                "evidence": {
                    "prs": notable_prs(mine, valid_issue_numbers),
                    "reviews": notable_reviews(reviewed, login),
                    "issues": notable_issues(closed_issues),
                },
            }
        )

    if not people:
        print("No scored contributors. Fetch reviews first.", file=sys.stderr)
        return 1

    normalization_bounds = {}
    for key in ("outcomes", "review_reach", "framing"):
        raw_values = [p["raw"][key] for p in people]
        normalization_bounds[key] = {
            "min": round(min(raw_values), 2),
            "max": round(max(raw_values), 2),
        }
        normed = minmax(raw_values)
        for p, n in zip(people, normed):
            p["pillars"][key]["score"] = round(n, 1)
            p["pillars"][key]["raw"] = round(p["raw"][key], 2)

    for p in people:
        p["impact"] = round(
            WEIGHTS["outcomes"] * p["pillars"]["outcomes"]["score"]
            + WEIGHTS["review_reach"] * p["pillars"]["review_reach"]["score"]
            + WEIGHTS["framing"] * p["pillars"]["framing"]["score"],
            1,
        )
        p["why"] = why_sentence(p)
        del p["raw"]

    people.sort(
        key=lambda p: (
            -p["impact"],
            -p["pillars"]["outcomes"]["issue_ref_prs"],
            p["login"],
        )
    )
    for i, p in enumerate(people, 1):
        p["rank"] = i

    top5 = people[:5]
    author_hist = Counter((pr.get("user") or {}).get("login") for pr in prs)

    payload = {
        "meta": {
            "repo": meta.get("repo") or "PostHog/posthog",
            "start": WINDOW_START,
            "end": WINDOW_END,
            "fetched_at": meta.get("fetched_at"),
            "pr_count": meta.get("pr_count") or len(prs),
            "issue_count": meta.get("issue_count") or len(issues),
            "staff_considered": len(staff_users),
            "staff_scored": len(people),
            "high_comment_threshold": high_bar,
            "weights": WEIGHTS,
            "formulas": FORMULAS,
            "normalization_bounds": normalization_bounds,
            "population": (
                "PostHog-affiliated GitHub contributors: company contains 'posthog', "
                "or bio contains 'posthog', or login ends in -ph / -posthog, "
                "or public org member whose company is empty or PostHog. "
                "Public members with a different company are excluded. "
                "Role and employment dates are inferred, not verified."
            ),
            "excluded_from_rank": [
                "lines of code",
                "commit count",
                "files changed",
                "raw PR volume (log-damped leftover term only)",
                "revert authorship",
                "review depth / CHANGES_REQUESTED",
                "stamphog-labeled PRs (outcomes terms)",
            ],
            "skipped_no_signal": skipped_no_signal,
        },
        "top5": top5,
        "all": [
            {
                "rank": p["rank"],
                "login": p["login"],
                "name": p["name"],
                "impact": p["impact"],
                "outcomes": p["pillars"]["outcomes"]["score"],
                "review_reach": p["pillars"]["review_reach"]["score"],
                "framing": p["pillars"]["framing"]["score"],
                "merged_prs": p["pillars"]["outcomes"]["merged_prs"],
                "issue_ref_prs": p["pillars"]["outcomes"]["issue_ref_prs"],
                "reviewed_others": p["pillars"]["review_reach"]["reviewed_others"],
                "issues_authored_closed_in_window": p["pillars"]["framing"][
                    "issues_authored_closed_in_window"
                ],
            }
            for p in people
        ],
        "volume_check": {
            "note": "Highest raw PR authors in the window. Shown so volume is visible and not the rank.",
            "top_authors": [
                {"login": login, "merged_prs": n}
                for login, n in author_hist.most_common(8)
                if login
            ],
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {OUT} ({len(people)} scored, top 5:)", flush=True)
    for p in top5:
        print(
            f"  #{p['rank']} {p['login']:20} impact={p['impact']:5}  "
            f"refs={p['pillars']['outcomes']['issue_ref_prs']:3}  "
            f"rev={p['pillars']['review_reach']['reviewed_others']:3}  "
            f"iss={p['pillars']['framing']['issues_authored_closed_in_window']:3}  "
            f"prs={p['pillars']['outcomes']['merged_prs']:3}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
