"""CockroachDB connection helper. One transaction per agent step; no
connection or cursor is ever held across a step boundary."""
import psycopg
import config


def connect():
    return psycopg.connect(config.DATABASE_URL, autocommit=False)
