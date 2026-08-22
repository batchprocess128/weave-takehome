-- Relational model for the cached PostHog/posthog GitHub dumps.
--
-- Teaching points (why not "just keep the JSON"):
--   1. reviews.json is reviewer → [full PR objects]. That duplicates ~8.5k PRs
--      and is why the file is 43MB. A (reviewer, pr) table is the real fact.
--   2. users.json is a profile census (high-signal authors ∪ org members), not
--      every PR/issue author. So author_login is a column, not a foreign key.
--   3. Labels are a many-to-many. 89 distinct values; filtering stamphog is a
--      join, not a JSON probe.
--
-- Idempotent: load_db.py applies this file on every run.

DROP VIEW IF EXISTS review_reach;
DROP VIEW IF EXISTS pr_volume;
DROP TABLE IF EXISTS reviews;
DROP TABLE IF EXISTS pr_labels;
DROP TABLE IF EXISTS issue_labels;
DROP TABLE IF EXISTS prs;
DROP TABLE IF EXISTS issues;
DROP TABLE IF EXISTS org_members;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS fetch_meta;

CREATE TABLE fetch_meta (
    repo        TEXT NOT NULL,
    window_start DATE NOT NULL,
    window_end  DATE NOT NULL,
    fetched_at  TIMESTAMPTZ,
    pr_count    INTEGER,
    issue_count INTEGER,
    user_count  INTEGER,
    staff_count INTEGER
);

-- Profile census from users.json, plus flags computed with the same
-- affiliation rules as scripts/analyze.py (inferred, not an HR roster).
CREATE TABLE users (
    login              TEXT PRIMARY KEY,
    name               TEXT,
    company            TEXT,
    type               TEXT,
    bio                TEXT,
    avatar_url         TEXT,
    html_url           TEXT,
    merged_pr_count    INTEGER NOT NULL DEFAULT 0,
    is_public_member   BOOLEAN NOT NULL DEFAULT FALSE,
    is_affiliated      BOOLEAN NOT NULL DEFAULT FALSE
);

-- Public PostHog org members (members.json). Source for is_public_member.
CREATE TABLE org_members (
    login TEXT PRIMARY KEY
);

CREATE TABLE prs (
    number       INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    body         TEXT NOT NULL DEFAULT '',
    state        TEXT,
    comments     INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ,
    closed_at    TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ,
    html_url     TEXT NOT NULL,
    author_login TEXT,
    author_type  TEXT
);

CREATE TABLE issues (
    number       INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    body         TEXT NOT NULL DEFAULT '',
    state        TEXT,
    comments     INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ,
    closed_at    TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ,
    html_url     TEXT NOT NULL,
    author_login TEXT,
    author_type  TEXT
);

CREATE TABLE pr_labels (
    pr_number INTEGER NOT NULL REFERENCES prs (number) ON DELETE CASCADE,
    label     TEXT NOT NULL,
    PRIMARY KEY (pr_number, label)
);

CREATE TABLE issue_labels (
    issue_number INTEGER NOT NULL REFERENCES issues (number) ON DELETE CASCADE,
    label        TEXT NOT NULL,
    PRIMARY KEY (issue_number, label)
);

-- One row per (reviewer, merged PR) from GitHub `reviewed-by:LOGIN` search.
-- Self-reviews are stored; exclude them in queries (see review_reach).
CREATE TABLE reviews (
    reviewer_login TEXT NOT NULL,
    pr_number      INTEGER NOT NULL REFERENCES prs (number) ON DELETE CASCADE,
    PRIMARY KEY (reviewer_login, pr_number)
);

CREATE INDEX prs_author_idx ON prs (author_login);
CREATE INDEX prs_closed_idx ON prs (closed_at);
CREATE INDEX issues_author_idx ON issues (author_login);
CREATE INDEX issues_closed_idx ON issues (closed_at);
CREATE INDEX reviews_pr_idx ON reviews (pr_number);
CREATE INDEX pr_labels_label_idx ON pr_labels (label);

-- Volume ≠ impact. The dashboard ranks on leverage, not this count.
CREATE VIEW pr_volume AS
SELECT author_login, COUNT(*) AS merged_prs
FROM prs
WHERE author_login IS NOT NULL
GROUP BY author_login;

-- Review reach as defined in the take-home: others' PRs, plus distinct authors.
CREATE VIEW review_reach AS
SELECT
    r.reviewer_login,
    COUNT(*) FILTER (WHERE p.author_login IS DISTINCT FROM r.reviewer_login)
        AS reviewed_others,
    COUNT(DISTINCT p.author_login)
        FILTER (
            WHERE p.author_login IS DISTINCT FROM r.reviewer_login
              AND p.author_login IS NOT NULL
        ) AS distinct_authors
FROM reviews r
JOIN prs p ON p.number = r.pr_number
GROUP BY r.reviewer_login;
