# PostHog Engineering Impact Dashboard

Weave take-home: identify the most impactful engineers on [`PostHog/posthog`](https://github.com/PostHog/posthog) from the last 90+ days.

**Dashboard:** published from `main:/docs` with GitHub Pages. Replace this line with the Pages URL after the first push.

**Time:** timer started 2026-08-18 11:02 PDT. Reported at submit.

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
docs/index.html        # one-page dashboard (no build step)
docs/data.json         # precomputed analysis (dashboard reads this)
data/raw/              # fetched GitHub payloads (not required at runtime)
```

## Hosting

GitHub Pages serves the committed `docs/` directory without a build step.

After pushing the repository, open **Settings → Pages**, choose **Deploy from a branch**, then select `main` and `/docs`. Verify both the page and `data.json` in a logged-out browser before submitting.

## Validation

- Dataset: 13,475 merged PRs and 969 relevant issues from 2026-05-20 through 2026-08-18.
- Ranking: 106 inferred PostHog-affiliated contributors considered; 105 scored because one had no PR or review signal.
- Evidence: every top-five profile includes authored PR, reviewed-PR, and (where present) issue links.
- Sensitivity: Arthur leads outcomes and framing; the review-reach leader is Georges-Antoine Assi. Tom Owers ranks third in the combined model, fifth on outcomes and second on review reach. His 1,160 `stamphog`-labeled PRs are excluded from outcomes.
- Reproducibility: `python3 scripts/analyze.py` regenerates `docs/data.json` deterministically from the cached raw inputs.

**Data constraints we designed around:** ~13.5k merged PRs in 90 days; GitHub search caps at 1,000 hits per query and 30 req/min. Fetch slices dates into 4–5 day windows and sleeps on the rate limit.

## Caveats (shown on the dashboard too)

- GitHub is a proxy. It cannot see Slack, Linear, customer calls, or incidents.
- Pairing and AI-assisted PRs attribute to the author on the PR.
- Affiliation is inferred from GitHub company, bio, login suffix, or public membership. Not an HR roster.
- Review reach is `reviewed-by` search hits. We did not fetch review bodies or CHANGES_REQUESTED.
- Issue-ref PRs are a text parser, not GitHub's linked-issue graph.
- Conversation comments are search `comments`, not review-discussion depth.
- Other PostHog repositories are excluded.
- Submission also needs a coding-agent session export (reserved at the end).

## Evaluation notes

The page is meant to be understood at a glance, validated by clicking through to real PRs, and loaded in well under 10 seconds (no live GitHub calls).
