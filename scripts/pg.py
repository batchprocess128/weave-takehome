"""Read local Postgres into a pandas DataFrame.

    uv sync
    uv run python -c "from scripts.pg import read_df; print(read_df('SELECT COUNT(*) FROM prs'))"

Or a REPL:

    from scripts.pg import read_df
    df = read_df("SELECT * FROM review_reach ORDER BY reviewed_others DESC LIMIT 10")
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import psycopg
from psycopg.rows import dict_row

DEFAULT_URL = "postgresql://weave:weave@localhost:5432/weave"


def read_df(sql: str, params: Any = None) -> pd.DataFrame:
    """Run a SQL query and return a DataFrame. params is a psycopg argument tuple/dict."""
    url = os.environ.get("DATABASE_URL") or DEFAULT_URL
    with psycopg.connect(url, row_factory=dict_row) as conn:
        rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame(rows)


if __name__ == "__main__":
    volume = read_df(
        """
        SELECT author_login, merged_prs
        FROM pr_volume
        ORDER BY merged_prs DESC
        LIMIT 8
        """
    )
    print(volume.to_string(index=False))
