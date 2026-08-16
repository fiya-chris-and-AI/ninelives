"""
F4: pre-seeded episodic memories for Beat 4. Curated (disclosed, not
live-generated) so the brain monitor and recall query have real,
vector-searchable content to demonstrate against independent of any single
live run's output. Attaches to a dedicated seed job so it never collides
with a real research job's own findings.
Run: .venv/bin/python scripts/seed_memories.py
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db
import embeddings

SEED_JOB_GOAL = "Curated prior knowledge: resilience patterns across engineered and biological systems."

SEED_MEMORIES = [
    "Distributed consensus protocols (Raft, Paxos) tolerate node loss by "
    "requiring a strict majority quorum before any write commits — the "
    "surviving majority always outnumbers whatever is missing.",
    "Write-ahead logging is the mechanism every crash-safe database shares: "
    "durably record the intent to change before applying the change, so "
    "recovery can replay from the log and reach the exact state that would "
    "have existed had the crash never happened.",
    "Triple modular redundancy (used in spacecraft flight computers) runs "
    "identical computation on independent processors and takes a majority "
    "vote, treating disagreement between copies as the expected signal of "
    "a failure rather than an exceptional event.",
    "Biological systems that survive repeated stress, from immune memory "
    "cells to dormant bacterial persisters, share one strategy: keep a "
    "small, low-cost reserve of state alive through the crisis and rebuild "
    "from that reserve rather than starting over.",
    "A system's resilience is not fixed — it is a race between how fast it "
    "recovers from a single failure and how frequently failures arrive; "
    "recovery that outpaces individual failures can still lose to a high "
    "enough failure rate.",
]


def main():
    job_id = str(uuid.uuid4())

    def create_seed_job(conn):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (id, goal, status, memory_mode) VALUES (%s, %s, 'done', 'persistent')",
                (job_id, SEED_JOB_GOAL),
            )
            cur.execute(
                "INSERT INTO job_state (job_id, step, total_steps, partial_output) "
                "VALUES (%s, %s, %s, '')",
                (job_id, len(SEED_MEMORIES) + 1, len(SEED_MEMORIES)),
            )

    db.run_txn(create_seed_job)

    for i, content in enumerate(SEED_MEMORIES, start=1):
        vec = embeddings.embed(content)

        def insert_seed(conn, step=i, text=content, embedding=vec):
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO memory_events (job_id, region, step, kind, content, embedding, source, curated) "
                    "VALUES (%s, %s, %s, 'seed', %s, %s, 'curated-seed', true)",
                    (job_id, "seed", step, text, str(embedding)),
                )

        db.run_txn(insert_seed)

    print(f"seeded {len(SEED_MEMORIES)} curated memories under job {job_id}")


if __name__ == "__main__":
    main()
