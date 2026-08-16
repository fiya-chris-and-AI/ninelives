"""
M0 spike: minimal transactional write/read loop.
Creates a job, streams one LLM step, persists chunks transactionally as
they arrive, embeds a memory event, and reads everything back.
Run: .venv/bin/python scripts/spike_m0.py
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
import db
import llm
import embeddings


def main():
    job_id = str(uuid.uuid4())
    goal = "Summarize why transactional state matters for AI agents."

    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (id, goal, status) VALUES (%s, %s, 'running')",
                (job_id, goal),
            )
            cur.execute(
                "INSERT INTO job_state (job_id, step, total_steps, partial_output) "
                "VALUES (%s, 0, 1, '')",
                (job_id,),
            )
        conn.commit()
    print(f"job {job_id} created")

    seq = 0
    full_text = ""
    for delta in llm.step_stream(f"In one sentence: {goal}"):
        full_text += delta
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO output_chunks (job_id, seq, step, text, region) "
                    "VALUES (%s, %s, 0, %s, %s)",
                    (job_id, seq, delta, "local-spike"),
                )
                cur.execute(
                    "UPDATE job_state SET partial_output = partial_output || %s, "
                    "updated_at = now() WHERE job_id = %s",
                    (delta, job_id),
                )
            conn.commit()
        seq += 1
    print(f"streamed {seq} chunks, {len(full_text)} chars: {full_text!r}")

    vec = embeddings.embed(full_text)
    print(f"embedded: dim={len(vec)} (config expects {config.EMBEDDING_DIM})")
    assert len(vec) == config.EMBEDDING_DIM, "embedding dim mismatch vs schema"

    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO memory_events (job_id, region, step, kind, content, embedding, source) "
                "VALUES (%s, %s, 0, 'finding', %s, %s, 'spike')",
                (job_id, "local-spike", full_text, str(vec)),
            )
            cur.execute(
                "UPDATE job_state SET step = 1, updated_at = now() WHERE job_id = %s",
                (job_id,),
            )
            cur.execute("UPDATE jobs SET status = 'done' WHERE id = %s", (job_id,))
        conn.commit()
    print("memory event written, job marked done")

    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT step, partial_output FROM job_state WHERE job_id = %s", (job_id,)
            )
            step, partial = cur.fetchone()
            cur.execute(
                "SELECT count(*) FROM output_chunks WHERE job_id = %s", (job_id,)
            )
            chunk_count = cur.fetchone()[0]
            cur.execute(
                "SELECT content, source FROM memory_events WHERE job_id = %s", (job_id,)
            )
            mem_content, mem_source = cur.fetchone()

    assert step == 1
    assert partial == full_text
    assert chunk_count == seq
    assert mem_content == full_text
    print(f"READ-BACK VERIFIED: step={step}, chunks={chunk_count}, "
          f"partial_output matches stream, memory_events row present (source={mem_source})")
    print("M0 TRANSACTIONAL WRITE/READ LOOP: GO")


if __name__ == "__main__":
    main()
