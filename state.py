"""
Shared read-side queries for the current demo job/lease — used by arena.py
(kill endpoint, status snapshot) and worker.py (which job to work on).
Write-side step logic stays in worker.py; this module only reads, except
for get_or_create_demo_job's atomic claim-or-create.
"""
import uuid

import db


def get_or_create_demo_job(goal: str, total_steps: int) -> str:
    """Returns the id of "the" shared demo job, creating one if none is
    running. Safe under concurrent callers (two independently-deployed
    worker services, no other coordination) via SELECT ... FOR UPDATE on
    the demo_pointer singleton row under CockroachDB SERIALIZABLE — the
    same pattern worker.py already uses for the lease table."""
    def txn(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT job_id FROM demo_pointer WHERE id = 1 FOR UPDATE")
            row = cur.fetchone()
            if row and row[0] is not None:
                cur.execute("SELECT status FROM jobs WHERE id = %s", (row[0],))
                status_row = cur.fetchone()
                if status_row and status_row[0] == "running":
                    return str(row[0])

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
                cur.execute("INSERT INTO demo_pointer (id, job_id) VALUES (1, %s)", (new_id,))
            else:
                cur.execute("UPDATE demo_pointer SET job_id = %s WHERE id = 1", (new_id,))
            return new_id

    return db.run_txn(txn)


def get_demo_job_id() -> str | None:
    def txn(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT job_id FROM demo_pointer WHERE id = 1")
            row = cur.fetchone()
            return str(row[0]) if row and row[0] else None

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
