-- Example queries for the local weave database.
-- Run:  docker exec -i weave-postgres psql -U weave -d weave < db/queries.sql
-- Or:   psql "$DATABASE_URL" -f db/queries.sql

-- 1. Did the load work?
SELECT repo, window_start, window_end, pr_count, issue_count, user_count
FROM fetch_meta;

SELECT
    (SELECT COUNT(*) FROM prs) AS prs,
    (SELECT COUNT(*) FROM issues) AS issues,
    (SELECT COUNT(*) FROM users) AS users,
    (SELECT COUNT(*) FROM reviews) AS review_pairs,
    (SELECT COUNT(*) FROM pr_labels) AS pr_labels;

-- 2. Volume leaders. Shown so raw PR count is visible and is not the rank.
SELECT author_login, merged_prs
FROM pr_volume
ORDER BY merged_prs DESC
LIMIT 8;

-- 3. How much of the window is stamphog automation?
SELECT
    COUNT(*) AS merged_prs,
    COUNT(*) FILTER (WHERE l.label = 'stamphog') AS stamphog_prs,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE l.label = 'stamphog') / COUNT(*),
        1
    ) AS stamphog_pct
FROM prs p
LEFT JOIN pr_labels l ON l.pr_number = p.number AND l.label = 'stamphog';

-- 4. Review reach (log-damped in analyze.py; raw counts here).
SELECT
    reviewer_login,
    reviewed_others,
    distinct_authors
FROM review_reach
ORDER BY reviewed_others DESC
LIMIT 10;

-- 5. Problem framing: issues the person authored whose closed_at is in-window.
SELECT
    i.author_login,
    COUNT(*) AS issues_authored_and_closed
FROM issues i
CROSS JOIN fetch_meta m
WHERE i.author_login IS NOT NULL
  AND i.closed_at::date BETWEEN m.window_start AND m.window_end
GROUP BY i.author_login
ORDER BY issues_authored_and_closed DESC
LIMIT 10;

-- 6. Affiliated engineers only — same population the dashboard scores.
SELECT login, name, company, merged_pr_count, is_public_member
FROM users
WHERE is_affiliated
ORDER BY merged_pr_count DESC
LIMIT 15;

-- 7. One person, three signals. Swap the login to walk a profile.
SELECT
    u.login,
    u.name,
    (SELECT COUNT(*) FROM prs p WHERE p.author_login = u.login) AS merged_prs,
    (SELECT reviewed_others FROM review_reach r WHERE r.reviewer_login = u.login)
        AS reviewed_others,
    (
        SELECT COUNT(*)
        FROM issues i
        CROSS JOIN fetch_meta m
        WHERE i.author_login = u.login
          AND i.closed_at::date BETWEEN m.window_start AND m.window_end
    ) AS issues_closed_in_window
FROM users u
WHERE u.login = 'jakesciotto';
