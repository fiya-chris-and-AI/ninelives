"""
Live signals for the arena, all built on one generic changefeed/poll
primitive (stream_table):

- F7 brain monitor: memory_events writes (stream_memory_writes)
- F10 worker panes: output_chunks, per-region streamed text (stream_output_chunks)
- F10 active-worker indicator: lease ownership changes (stream_lease)

Primary: a CockroachDB core changefeed (EXPERIMENTAL CHANGEFEED, no sink,
no enterprise license) streamed row-by-row over the SQL connection via
psycopg's server-side cursor mode. Documented fallback (brief's own
Failure States section): 1s polling by a monotonic column, used
automatically if the changefeed can't be opened — visually identical on
the panel.
"""
import json
import time
from typing import Iterator

import psycopg

import config
import db


def stream_changefeed(table: str) -> Iterator[dict]:
    """Yields one dict per row written to `table`, as CockroachDB emits
    it. Raises if the changefeed can't be opened at all (cluster tier
    without the feature); a mid-stream failure after that point is left
    to the caller to notice and fall back on the next connection
    attempt."""
    conn = psycopg.connect(config.DATABASE_URL, autocommit=True)
    try:
        with conn.cursor() as cur:
            sql = f"EXPERIMENTAL CHANGEFEED FOR {table} WITH resolved='1s'"
            for _table, _key, value in cur.stream(sql):
                if value is None:
                    continue
                payload = json.loads(value)
                after = payload.get("after")
                if after is None:
                    continue  # resolved-timestamp heartbeat or delete marker
                yield after
    finally:
        conn.close()


def poll_table(table: str, order_col: str, select_cols: str, poll_seconds: float = None) -> Iterator[dict]:
    """Fallback: reads rows newer than the last seen `order_col` value on
    a fixed cadence."""
    poll_seconds = poll_seconds if poll_seconds is not None else config.MONITOR_POLL_SECONDS
    last_val = None
    while True:
        def txn(conn, last_val=last_val):
            with conn.cursor() as cur:
                if last_val is None:
                    cur.execute(f"SELECT {select_cols} FROM {table} ORDER BY {order_col} DESC LIMIT 1")
                else:
                    cur.execute(
                        f"SELECT {select_cols} FROM {table} WHERE {order_col} > %s ORDER BY {order_col} ASC",
                        (last_val,),
                    )
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

        rows = db.run_txn(txn)
        for row in rows:
            last_val = row[order_col]
            yield {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}
        time.sleep(poll_seconds)


def stream_table(table: str, order_col: str, select_cols: str, strip_fields=()) -> Iterator[dict]:
    """Entry point for one live signal. Uses the changefeed unless
    config.MONITOR_MODE forces polling, or the changefeed fails to open —
    same config-driven fallback pattern as the LLM/embedding provider
    switches."""
    def _strip(row):
        for f in strip_fields:
            row.pop(f, None)
        return row

    if config.MONITOR_MODE == "poll":
        for row in poll_table(table, order_col, select_cols):
            yield _strip(row)
        return
    try:
        for row in stream_changefeed(table):
            yield _strip(row)
    except Exception:
        for row in poll_table(table, order_col, select_cols):
            yield _strip(row)


def stream_memory_writes() -> Iterator[dict]:
    """F7. 384-1024 embedding floats stripped — the panel never needs them."""
    yield from stream_table(
        "memory_events", "ts",
        "id, job_id, ts, region, step, kind, content, source, curated",
        strip_fields=("embedding",),
    )


def stream_output_chunks() -> Iterator[dict]:
    """F10 worker panes: text deltas as they're persisted, per region."""
    yield from stream_table(
        "output_chunks", "created_at",
        "job_id, step, seq, text, region, created_at",
    )


def stream_lease() -> Iterator[dict]:
    """F10 active-worker indicator. The lease row is renewed every
    LEASE_HEARTBEAT_SECONDS by a live worker (see worker.py), which would
    otherwise flood this feed with no-op renewals — only forwarded on an
    actual ownership change (a claim, i.e. a kill happened)."""
    last_owner = None
    for row in stream_table("lease", "expires_at", "job_id, owner, region, control_addr, expires_at"):
        if row.get("owner") == last_owner:
            continue
        last_owner = row.get("owner")
        yield row
