# Local Postgres for the PostHog impact dataset

This track is a **tutorial and portfolio piece**. It is not required to view the dashboard.

The dashboard still reads `docs/data.json`. Scoring stays in `scripts/analyze.py`. Postgres is how you inspect the same cached GitHub dumps with SQL after you have fetched them once.

## Why a database server

The raw files are already on disk (`data/raw/`, ~97MB of JSON). A local server is useful when you want to:

- join PRs, labels, reviewers, and profiles without loading 48MB arrays into Python
- keep a process you can connect to from `psql`, a GUI, or another language
- show a normal relational design on a real GitHub extract

Postgres over Mongo: the interesting questions are joins (who reviewed whose PRs, which of those are stamphog, who is affiliated). Postgres over SQLite: you asked for a server you can run locally; Compose is the usual way to show that.

## What the JSON gets wrong

| File | Shape on disk | Problem | Table |
|---|---|---|---|
| `prs.json` | list of 13,475 objects | nested `user`, labels as a string array | `prs` + `pr_labels` |
| `issues.json` | same shape, 969 rows | same | `issues` + `issue_labels` |
| `reviews.json` | `{login: [PR, PR, …]}` | **43MB of duplicated PRs** | `reviews(reviewer_login, pr_number)` |
| `users.json` | `{login: profile}` | not every author is in here | `users` (no FK from `author_login`) |
| `members.json` | list of 27 logins | affiliation input, not employment | `org_members` |

`users.json` is a profile census: authors with enough merged PRs, unioned with public org members. Eight PR authors and a couple hundred issue authors have no profile row. That is why `prs.author_login` is a column, not `REFERENCES users(login)`.

## Dependencies (uv)

Optional packages live in `pyproject.toml` dependency groups — not in the take-home core:

| Group | Packages | Used for |
|---|---|---|
| `db` | psycopg, pandas | `load_db.py`, `pg.py`, SQL → DataFrame |
| `notebook` | jupyterlab, ipykernel, scikit-learn | `PostHogDataEDA.ipynb` exploration |

```bash
uv sync                              # install db + notebook groups (default)
uv add scikit-learn                  # example: add a package to the project
uv run python scripts/load_db.py     # always runs inside the project .venv
```

Commit `pyproject.toml` and `uv.lock` so the environment is reproducible. `.venv/` stays gitignored.

## Schema

```mermaid
erDiagram
    fetch_meta {
        date window_start
        date window_end
    }
    users {
        text login PK
        boolean is_affiliated
        boolean is_public_member
    }
    org_members {
        text login PK
    }
    prs {
        int number PK
        text author_login
    }
    issues {
        int number PK
        text author_login
    }
    pr_labels {
        int pr_number PK
        text label PK
    }
    issue_labels {
        int issue_number PK
        text label PK
    }
    reviews {
        text reviewer_login PK
        int pr_number PK
    }
    users ||--o{ reviews : "reviewer"
    prs ||--o{ reviews : "reviewed PR"
    prs ||--o{ pr_labels : has
    issues ||--o{ issue_labels : has
    org_members ||--o| users : "same login"
```

Two views ship with the schema:

- `pr_volume` — raw merged-PR counts. The dashboard shows this so volume is visible and **not** the rank.
- `review_reach` — `reviewed-by` hits on other people's PRs, plus distinct authors. Same definition as the take-home, without the log damping.

`users.is_affiliated` is computed at load time with `scripts/analyze.affiliated`, so SQL and the page agree on the scored population.

## Run it

Needs Docker Desktop (you do not need a local `postgres` install).

```bash
docker compose up -d
uv sync
uv run python scripts/load_db.py
```

`load_db.py` reapplies `db/schema.sql` every run, then inserts. Safe to rerun after a new fetch.

Connect:

```bash
docker exec -it weave-postgres psql -U weave -d weave
```

Or from the host, if you have `psql`:

```bash
psql postgresql://weave:weave@localhost:5432/weave
```

Stop / wipe:

```bash
docker compose stop
docker compose down -v    # deletes the volume
```

## Query it

```bash
docker exec -i weave-postgres psql -U weave -d weave < db/queries.sql
```

`db/queries.sql` walks the same questions the dashboard answers: load sanity, volume leaders, stamphog share, review reach, in-window framed issues, affiliated users, and one person across three signals.

## Into a DataFrame

```python
from scripts.pg import read_df

df = read_df("""
    SELECT reviewer_login, reviewed_others, distinct_authors
    FROM review_reach
    ORDER BY reviewed_others DESC
    LIMIT 10
""")
df.head()
```

Parameterized:

```python
df = read_df(
    "SELECT number, title, comments FROM prs WHERE author_login = %s LIMIT 5",
    ("jakesciotto",),
)
```

One-shot:

```bash
uv run python scripts/pg.py
```

## Notebook

Always start Jupyter from the project env (not Homebrew):

```bash
uv run jupyter lab
```

Register the kernel **once** (points at `.venv/bin/python`; new `uv add` packages show up automatically):

```bash
uv run python -m ipykernel install --user --name=weave --display-name="Python (weave)"
```

In the notebook: **Kernel → Select Kernel → Python (weave)**.

Sanity check in a cell:

```python
import sys
sys.executable   # should end in weave-takehome/.venv/bin/python
```

## What this is not

- Not a rewrite of the impact model. Min-max normalization and the editorial writeups stay in Python.
- Not live GitHub. You still run `scripts/fetch.py` (needs `gh auth login`) to fill `data/raw/`. Those JSON files are gitignored.
- Not production. Default password is `weave`, bound to localhost.
