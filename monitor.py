"""
F7: brain monitor. Yields memory_events writes live, as they land.

Primary: a CockroachDB core changefeed (EXPERIMENTAL CHANGEFEED, no sink,
no enterprise license) streamed row-by-row over the SQL connection via
psycopg's server-side cursor mode. Documented fallback (brief's own
Failure States section): 1s polling by ts, used automatically if the
changefeed can't be opened — visually identical on the panel.
"""
import json
import time
from typing import Iterator

import psycopg

import config
import db

CHANGEFEED_SQL = "EXPERIMENTAL CHANGEFEED FOR memory_events WITH resolved='1s'"


def stream_changefeed() -> Iterator[dict]:
    """Yields one dict per memory_events write, as CockroachDB emits it.
    Raises if the changefeed can't be opened at all (cluster tier without
    the feature); a mid-stream failure after that point is left to the
    caller to notice and fall back on the next connection attempt."""
    conn = psycopg.connect(config.DATABASE_URL, autocommit=True)
    try:
        with conn.cursor() as cur:
            for _table, _key, value in cur.stream(CHANGEFEED_SQL):
                if value is None:
                    continue
                payload = json.loads(value)
                after = payload.get("after")
                if after is None:
                    continue  # resolved-timestamp heartbeat or delete marker
                after.pop("embedding", None)  # 384-1024 floats; the panel never needs it
                yield after
    finally:
        conn.close()


def poll_new_events(poll_seconds: float = None) -> Iterator[dict]:
    """Fallback: reads memory_events rows newer than the last seen `ts`
    on a fixed cadence."""
    poll_seconds = poll_seconds if poll_seconds is not None else config.MONITOR_POLL_SECONDS
    last_ts = None
    while True:
        def txn(conn, last_ts=last_ts):
            with conn.cursor() as cur:
                if last_ts is None:
                    cur.execute(
                        "SELECT id, job_id, ts, region, step, kind, content, source, curated "
                        "FROM memory_events ORDER BY ts DESC LIMIT 1"
                    )
                else:
                    cur.execute(
                        "SELECT id, job_id, ts, region, step, kind, content, source, curated "
                        "FROM memory_events WHERE ts > %s ORDER BY ts ASC",
                        (last_ts,),
                    )
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

        rows = db.run_txn(txn)
        for row in rows:
            last_ts = row["ts"]
            yield {
                "id": str(row["id"]),
                "job_id": str(row["job_id"]),
                "ts": row["ts"].isoformat(),
                "region": row["region"],
                "step": row["step"],
                "kind": row["kind"],
                "content": row["content"],
                "source": row.get("source"),
                "curated": row.get("curated", False),
            }
        time.sleep(poll_seconds)


def stream_memory_writes() -> Iterator[dict]:
    """F7 entry point. Uses the changefeed unless config.MONITOR_MODE
    forces polling, or the changefeed fails to open — same config-driven
    fallback pattern as the LLM/embedding provider switches."""
    if config.MONITOR_MODE == "poll":
        yield from poll_new_events()
        return
    try:
        yield from stream_changefeed()
    except Exception:
        yield from poll_new_events()
