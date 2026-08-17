"""Apply schema.sql to the CockroachDB Cloud cluster in DATABASE_URL.
Run: .venv/bin/python scripts/setup_db.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
import db


def main():
    schema_path = os.path.join(os.path.dirname(__file__), "..", "schema", "schema.sql")
    with open(schema_path) as f:
        sql = f.read().replace("{{VECTOR_DIM}}", str(config.EMBEDDING_DIM))

    # statement_timeout_ms=0 (disabled): db.connect()'s default 3s cap is
    # sized for worker/arena transactions (single small DML statements),
    # not this one-time multi-statement DDL apply — it briefly got itself
    # cancelled mid-schema-creation against the live cluster otherwise
    # (round 2, 2026-08-16).
    with db.connect(statement_timeout_ms=0) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()

    print(f"Schema applied. embedding dim={config.EMBEDDING_DIM}")


if __name__ == "__main__":
    main()
