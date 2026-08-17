"""CockroachDB connection helper. One transaction per agent step; no
connection or cursor is ever held across a step boundary."""
import time
import psycopg
import config

MAX_RETRIES = 5

# Round 2 re-Examine finding (2026-08-16, examiner_report.md P1): a live
# kill-and-resume test measured a 24.9s lease-claim stall (vs. the ≤5s
# bar) — 8-10x this app's own designed worst case. Root-cause hypothesis:
# a SIGKILL landing mid-transaction leaves a write intent on the `lease`
# row; a plain `psycopg.connect()` with no keepalives or statement
# timeout lets a subsequent claim attempt block indefinitely waiting for
# CockroachDB (or its Cloud proxy) to notice the dead session and release
# it — a wait bounded by server-side detection latency, not by anything
# LEASE_TTL_SECONDS/STANDBY_POLL_SECONDS control. Not confirmed via
# direct session inspection; see the P1 write-up for the honest caveat.
# Keepalives + a statement timeout don't provably fix the server-side
# detection latency, but they do turn "one call blocks for an unknown,
# possibly unbounded time" into "every call is capped, and a capped
# failure is treated as a retry, not a crash" (worker.py's
# claim_or_renew_lease). Safe as the DEFAULT for every worker/arena
# transaction (all single small DML statements). NOT safe as a blanket
# default for every caller: scripts/setup_db.py applies the full,
# multi-statement schema.sql in one execute() call, which briefly
# exceeded 3s and got itself cancelled mid-DDL against the live cluster
# (round 2, 2026-08-16) — that caller must pass statement_timeout_ms=0
# (disabled) explicitly.
STATEMENT_TIMEOUT_MS = 3000


def connect(statement_timeout_ms: int = STATEMENT_TIMEOUT_MS):
    return psycopg.connect(
        config.DATABASE_URL,
        autocommit=False,
        keepalives=1,
        keepalives_idle=5,
        keepalives_interval=2,
        keepalives_count=2,
        options=f"-c statement_timeout={statement_timeout_ms}",
    )


def run_txn(fn):
    """Run fn(conn) inside a transaction, retrying on CockroachDB
    serialization failures (SQLSTATE 40001) per CockroachDB's documented
    client-side retry contract. Concurrent primary/standby lease access
    makes this a routine, expected event, not an error condition."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        conn = connect()
        try:
            result = fn(conn)
            conn.commit()
            return result
        except psycopg.errors.SerializationFailure as e:
            conn.rollback()
            last_error = e
            time.sleep(0.05 * (2 ** attempt))
        finally:
            conn.close()
    raise last_error
