"""CockroachDB connection helper. One transaction per agent step; no
connection or cursor is ever held across a step boundary."""
import time
import psycopg
import config

MAX_RETRIES = 5

# Round 2 re-Examine finding (2026-08-16, examiner_report.md P1): a live
# kill-and-resume test measured a 24.9s lease-claim stall (vs. the ≤5s
# bar). Initial hypothesis was a SIGKILL-abandoned write intent on the
# `lease` row blocking a subsequent claim. Round 3 investigation
# (2026-08-17, DECISION_LOG.md) DISPROVED that hypothesis with direct
# evidence: crdb_internal.cluster_locks and SHOW SESSIONS showed zero
# activity for the entire duration of an induced stall — the real cause
# was ECS Fargate task-replacement time exceeding config.KILL_COOLDOWN_
# SECONDS (fixed there, not here). Keepalives + a statement timeout are
# kept anyway as legitimate, low-risk defense-in-depth — they bound
# every call's worst case and turn any future stuck-connection scenario
# into a retry instead of a crash — but they were never the fix for the
# stall this round chased. Safe as the DEFAULT for every worker/arena
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
