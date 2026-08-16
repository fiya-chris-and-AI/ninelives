"""
Wipe and reapply schema, clearing all jobs/state/leases/memory. Used both
as the dev migration tool and as `make demo-reset` (F4: clean demo state
in <30s).
Run: .venv/bin/python scripts/reset_demo.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db

DROP_ORDER = ["output_chunks", "memory_events", "lease", "job_state", "jobs"]


def main():
    with db.connect() as conn:
        with conn.cursor() as cur:
            for table in DROP_ORDER:
                cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        conn.commit()
    print("all tables dropped")

    import setup_db
    setup_db.main()


if __name__ == "__main__":
    main()
