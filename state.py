"""
Shared read-side queries for the current demo job/lease — used by arena.py
(kill endpoint, status snapshot) and worker.py (which job to work on).
Write-side step logic stays in worker.py; this module only reads, except
for get_or_create_demo_job's atomic claim-or-create.
"""
import uuid

import db


def get_or_create_demo_job(goal: str, total_steps: int, pause_seconds: float) -> dict:
    """Returns {"job_id": str, "resting": False} for a job ready to work
    on, or {"job_id": None, "resting": True, "seconds_left": float}
    during the idle pause between a finished job and the next one
    (burn-rate throttle, round 2 — see config.IDLE_PAUSE_*_SECONDS).
    Safe under concurrent callers (two independently-deployed worker
    services, no other coordination) via SELECT ... FOR UPDATE on the
    demo_pointer singleton row under CockroachDB SERIALIZABLE — the same
    pattern worker.py already uses for the lease table. Whichever caller
    first observes the job as done starts the pause window (writing
    resting_until); the other caller sees it already set and agrees,
    so both regions rest together instead of one silently starting a
    new job while the other idles."""
    def txn(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT job_id, resting_until FROM demo_pointer WHERE id = 1 FOR UPDATE")
            row = cur.fetchone()
            if row and row[0] is not None:
                job_id, resting_until = row
                cur.execute("SELECT status FROM jobs WHERE id = %s", (job_id,))
                status_row = cur.fetchone()
                if status_row and status_row[0] == "running":
                    return {"job_id": str(job_id), "resting": False}

                # Adversarial finding (round 2, 2026-08-16): status_row is
                # also None when the pointed-at job was deleted out from
                # under us (scripts/reset_demo.py drops `jobs` but not
                # `demo_pointer`) — that is NOT "the job finished", and
                # must not start an idle pause. Only a job that genuinely
                # ran to completion (status_row exists and isn't
                # 'running') earns the burn-rate throttle's rest window;
                # a vanished job skips straight to claiming a new one
                # below, so a mid-job demo reset still recovers in the
                # F4-promised <30s instead of a spurious 60-90s pause.
                if status_row is not None:
                    if resting_until is None:
                        # First caller to see this job as done: start the pause.
                        cur.execute(
                            "UPDATE demo_pointer SET resting_until = now() + (%s || ' seconds')::interval WHERE id = 1",
                            (pause_seconds,),
                        )
                        return {"job_id": None, "resting": True, "seconds_left": pause_seconds}

                    cur.execute("SELECT GREATEST(EXTRACT(EPOCH FROM (%s - now())), 0)", (resting_until,))
                    seconds_left = float(cur.fetchone()[0])
                    if seconds_left > 0:
                        return {"job_id": None, "resting": True, "seconds_left": seconds_left}
                    # Pause window elapsed — fall through and claim the next job.

            new_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO jobs (id, goal, status, memory_mode) VALUES (%s, %s, 'running', 'persistent')",
                (new_id, goal),
            )
            cur.execute(
                "INSERT INTO job_state (job_id, step, total_steps, partial_output) "
                "VALUES (%s, 1, %s, '')",
                (new_id, total_steps),
            )
            if row is None:
                cur.execute("INSERT INTO demo_pointer (id, job_id, resting_until) VALUES (1, %s, NULL)", (new_id,))
            else:
                cur.execute("UPDATE demo_pointer SET job_id = %s, resting_until = NULL WHERE id = 1", (new_id,))
            return {"job_id": new_id, "resting": False}

    return db.run_txn(txn)


def get_demo_job_id() -> str | None:
    """The current demo job's id, but only while it's actually running.
    During the idle pause between jobs (or before the first job has ever
    been created) this returns None, so arena.py's existing "no active
    job" path on /api/status and /api/kill is what a visitor honestly
    sees — not a stale id pointing at a finished job whose worker is
    resting, not dead."""
    def txn(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT j.id FROM demo_pointer dp JOIN jobs j ON j.id = dp.job_id "
                "WHERE dp.id = 1 AND j.status = 'running'"
            )
            row = cur.fetchone()
            return str(row[0]) if row else None

    return db.run_txn(txn)


def get_resting_status() -> dict | None:
    """None while a job is running (or none has ever been created yet).
    Otherwise {"resting_until": iso str, "seconds_left": float} — the F10
    arena UI's "next job starts shortly" resting state (burn-rate
    throttle, round 2)."""
    def txn(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT resting_until, GREATEST(EXTRACT(EPOCH FROM (resting_until - now())), 0) "
                "FROM demo_pointer WHERE id = 1 AND resting_until IS NOT NULL"
            )
            row = cur.fetchone()
            if row is None:
                return None
            resting_until, seconds_left = row
            return {"resting_until": resting_until.isoformat(), "seconds_left": float(seconds_left)}

    return db.run_txn(txn)


def get_active_lease(job_id: str) -> dict | None:
    """The current lease row for the demo job — owner/region/control_addr
    identify which worker is alive right now and how to reach it."""
    def txn(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT owner, region, control_addr, expires_at FROM lease WHERE job_id = %s",
                (job_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description]
            return dict(zip(cols, row))

    return db.run_txn(txn)


def get_job_snapshot(job_id: str) -> dict:
    """Initial state for a freshly-connected arena visitor: current step,
    lease/active-region, so the page doesn't sit blank until the next
    live event."""
    def txn(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT step, total_steps, partial_output FROM job_state WHERE job_id = %s",
                (job_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {"step": row[0], "total_steps": row[1], "partial_output": row[2]}

    state = db.run_txn(txn)
    if state is None:
        return {"job_id": None, "step": None, "total_steps": None, "lease": None}

    lease = get_active_lease(job_id)
    if lease is not None:
        lease = {
            "owner": lease["owner"],
            "region": lease["region"],
            "expires_at": lease["expires_at"].isoformat(),
        }
    return {"job_id": job_id, **state, "lease": lease}
