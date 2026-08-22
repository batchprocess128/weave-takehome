# PostHog Engineering Impact Dashboard

Weave take-home: identify the most impactful engineers on [`PostHog/posthog`](https://github.com/PostHog/posthog) from the last 90+ days.

**Dashboard:** https://batchprocess128.github.io/weave-takehome/

**Time:** 65 minutes 8 seconds (timer started 2026-08-18 11:02 PDT).

## What "impact" means

**Impact, as scored here, is leverage visible in GitHub on `PostHog/posthog`.** It is not employment status, seniority, or activity volume.

We do not rank on lines of code, commit count, files changed, or raw PR volume.

Three pillars. Every number on the page is produced by the formulas below.

| Pillar | Weight | What it actually measures |
|---|---|---|
| **Shipped outcomes** | 40% | Issue-closing-keyword PRs, bug/perf/security labels, high conversation-comment PRs (log), leftover PRs (log). Stamphog PRs excluded. No revert penalty. |
| **Review reach** | 35% | Merged PRs matching `reviewed-by:LOGIN`, excluding self-authored. Log-damped. Not unblocking. Not review depth. |
| **Problem framing** | 25% | Issues the person authored whose `closed_at` falls in the window. GitHub issues are a weak proxy (PostHog uses Linear). |

```
outcomes_raw      = 3*issue_ref_prs + 2*bug_only_prs + 4*ln(1+high_comment_prs) + ln(1+other_prs)
review_reach_raw  = ln(1+reviewed_others) + ln(1+distinct_authors)
framing_raw       = issues_authored_and_closed_in_window
pillar_norm       = 100 * (raw - min) / (max - min)   across the scored population
impact            = 0.40*outcomes_norm + 0.35*review_reach_norm + 0.25*framing_norm
```

**Who is scored:** PostHog-affiliated GitHub contributors. Company contains `posthog`, or bio contains `posthog`, or login ends in `-ph` / `-posthog`, or public org member whose company is empty or PostHog. Public members with a different company are excluded. Role and employment dates are inferred, not verified. Top five are checked by hand.

**Window:** 2026-05-20 through 2026-08-18. PRs: merged in window. Framing issues: authored by the person and closed in window.

**Repo scope:** `PostHog/posthog` only.

## How to run

```bash
# 1. Fetch last 90 days from GitHub (needs `gh auth login`)
python3 scripts/fetch.py

# 2. Score engineers → docs/data.json
python3 scripts/analyze.py

# 3. Serve the dashboard locally
python3 -m http.server 8080 --directory docs
```

## Repo layout

```
scripts/fetch.py       # GitHub search + profile lookup → data/raw/
scripts/analyze.py     # impact model → docs/data.json
scripts/load_db.py     # optional: data/raw/ → local Postgres
scripts/pg.py          # optional: SQL → pandas DataFrame
docs/index.html        # one-page dashboard (no build step)
docs/data.json         # precomputed analysis (dashboard reads this)
data/raw/              # fetched GitHub payloads (not required at runtime)
db/                    # schema, example queries, tutorial (optional track)
docker-compose.yml     # local Postgres 16
pyproject.toml         # uv deps (optional db + notebook groups)
```

## Local Postgres (optional tutorial)

The dashboard does not need a database. This track loads the same `data/raw/` dumps into Postgres so you can join PRs, labels, reviewers, and profiles with SQL.

Walkthrough, schema diagram, and example queries: **[db/README.md](db/README.md)**.

Dependencies are managed with [uv](https://docs.astral.sh/uv/). The take-home scripts (`fetch.py`, `analyze.py`) stay stdlib-only; `uv sync` only installs the optional `db` and `notebook` groups.

```bash
docker compose up -d
uv sync
uv run python scripts/load_db.py
docker exec -i weave-postgres psql -U weave -d weave < db/queries.sql
uv run jupyter lab    # notebook: pick kernel "Python (weave)" after one-time setup in db/README.md
```

## Hosting

GitHub Pages serves the committed `docs/` directory without a build step.

Pages publishes from `main:/docs`. Verify both the page and `data.json` in a logged-out browser before submitting.

## Validation

- Dataset: 13,475 merged PRs and 969 relevant issues from 2026-05-20 through 2026-08-18.
- Ranking: 106 inferred PostHog-affiliated contributors considered; 105 scored because one had no PR or review signal.
- Evidence: every top-five profile includes authored PR links, plus reviewed-PR and issue links wherever those signals exist.
- Sensitivity: Jake Sciotto leads outcomes; Arthur Moreira de Deus leads framing; Georges-Antoine Assi leads review reach. Tom Owers ranks fourth in the composite and second on review reach after 1,160 `stamphog`-labeled PRs are excluded from outcomes.
- Reproducibility: `python3 scripts/analyze.py` regenerates `docs/data.json` deterministically from the cached raw inputs.

**Data constraints we designed around:** ~13.5k merged PRs in 90 days; GitHub search caps at 1,000 hits per query and 30 req/min. Fetch slices dates into 4–5 day windows and sleeps on the rate limit.

## Caveats (shown on the dashboard too)

- GitHub is a proxy. It cannot see Slack, Linear, customer calls, or incidents.
- Pairing and AI-assisted PRs attribute to the author on the PR.
- Affiliation is inferred from GitHub company, bio, login suffix, or public membership. Not an HR roster.
- Review reach is `reviewed-by` search hits. We did not fetch review bodies or CHANGES_REQUESTED.
- Issue-ref PRs use a text parser, not GitHub's linked-issue graph. A reference must immediately follow the closing keyword and resolve to the relevant issue census, preventing nearby prose references from being counted.
- Conversation comments are search `comments`, not review-discussion depth.
- Other PostHog repositories are excluded.
- Submission also needs a coding-agent session export (reserved at the end).

## Evaluation notes

The page is meant to be understood at a glance, validated by clicking through to real PRs, and loaded in well under 10 seconds (no live GitHub calls).
