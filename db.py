"""CockroachDB connection helper. One transaction per agent step; no
connection or cursor is ever held across a step boundary."""
import time
import psycopg
import config

MAX_RETRIES = 5


def connect():
    return psycopg.connect(config.DATABASE_URL, autocommit=False)


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
