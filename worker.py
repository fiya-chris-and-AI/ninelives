"""
The agent loop. Persistent mode: one transaction per lease claim, one
transaction per ~1s of streamed output, one transaction per step
completion — the process is disposable, CockroachDB is the mind.
Ephemeral mode (--no-memory, F6): identical step logic, zero persistence;
state lives only in this process's memory and dies with it.

Usage:
    .venv/bin/python worker.py --region us-east-1 --job-id <uuid>
    .venv/bin/python worker.py --region eu-central-1 --job-id <uuid> --standby
    .venv/bin/python worker.py --region us-east-1 --no-memory
"""
import argparse
import os
import sys
import threading
import time
import uuid

import config
import control
import db
import llm
import embeddings
import research
import state

# Standby-mode prints (no per-token flush=True to piggyback on) would
# otherwise sit in Python's block buffer until it fills — invisible in
# CloudWatch until then. Line-buffer the whole process instead of adding
# flush=True to every print call.
sys.stdout.reconfigure(line_buffering=True)

CHUNK_FLUSH_SECONDS = 1.0


def create_job(goal: str, total_steps: int) -> str:
    job_id = str(uuid.uuid4())

    def txn(conn):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (id, goal, status, memory_mode) VALUES (%s, %s, 'running', 'persistent')",
                (job_id, goal),
            )
            cur.execute(
                "INSERT INTO job_state (job_id, step, total_steps, partial_output) "
                "VALUES (%s, 1, %s, '')",
                (job_id, total_steps),
            )

    db.run_txn(txn)
    return job_id


def claim_or_renew_lease(job_id: str, owner: str, region: str, control_addr: str = None) -> bool:
    """Returns True if this owner now holds the lease. control_addr (F10)
    is this worker's kill-control endpoint — written on every claim/renew
    so the arena's kill button always has a fresh address for whoever is
    currently active."""
    ttl = config.LEASE_TTL_SECONDS

    def txn(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT owner, expires_at < now() AS expired FROM lease WHERE job_id = %s FOR UPDATE", (job_id,))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO lease (job_id, owner, region, expires_at, control_addr) "
                    "VALUES (%s, %s, %s, now() + (%s || ' seconds')::interval, %s)",
                    (job_id, owner, region, ttl, control_addr),
                )
                return True
            current_owner, expired = row
            if current_owner == owner or expired:
                cur.execute(
                    "UPDATE lease SET owner = %s, region = %s, expires_at = now() + (%s || ' seconds')::interval, "
                    "control_addr = %s WHERE job_id = %s",
                    (owner, region, ttl, control_addr, job_id),
                )
                return True
            return False

    return db.run_txn(txn)


def read_state(job_id: str):
    def txn(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT step, total_steps, partial_output FROM job_state WHERE job_id = %s",
                (job_id,),
            )
            step, total_steps, partial_output = cur.fetchone()
            cur.execute(
                "SELECT content FROM memory_events WHERE job_id = %s AND kind IN ('finding', 'synthesis') "
                "ORDER BY step ASC",
                (job_id,),
            )
            findings = [r[0] for r in cur.fetchall()]
            cur.execute(
                "SELECT content FROM memory_events WHERE job_id = %s AND kind = 'plan'",
                (job_id,),
            )
            plan_row = cur.fetchone()
            plan_text = plan_row[0] if plan_row else ""
        return step, total_steps, plan_text, partial_output, findings

    return db.run_txn(txn)


def next_chunk_seq(job_id: str, step: int) -> int:
    def txn(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM output_chunks WHERE job_id = %s AND step = %s",
                (job_id, step),
            )
            return cur.fetchone()[0]

    return db.run_txn(txn)


def flush_chunk(job_id: str, step: int, seq: int, text: str, region: str, owner: str):
    """One transaction: persist the chunk, extend partial_output, renew the lease."""
    def txn(conn):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO output_chunks (job_id, seq, step, text, region) VALUES (%s, %s, %s, %s, %s)",
                (job_id, seq, step, text, region),
            )
            cur.execute(
                "UPDATE job_state SET partial_output = partial_output || %s, updated_at = now() WHERE job_id = %s",
                (text, job_id),
            )
            cur.execute(
                "UPDATE lease SET expires_at = now() + (%s || ' seconds')::interval WHERE job_id = %s AND owner = %s",
                (config.LEASE_TTL_SECONDS, job_id, owner),
            )

    db.run_txn(txn)


def finalize_step(job_id: str, step: int, total_steps: int, full_text: str, region: str, step_kind: str):
    """One transaction: embed + write the memory event, advance the step,
    clear partial_output for the next step, mark done if this was the last."""
    vec = embeddings.embed(full_text)

    def txn(conn):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO memory_events (job_id, region, step, kind, content, embedding, source) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (job_id, region, step, step_kind, full_text, str(vec), "agent"),
            )
            cur.execute(
                "UPDATE job_state SET step = %s, partial_output = '', updated_at = now() WHERE job_id = %s",
                (step + 1, job_id),
            )
            if step >= total_steps:
                cur.execute("UPDATE jobs SET status = 'done' WHERE id = %s", (job_id,))

    db.run_txn(txn)


def step_kind_for(step_index: int) -> str:
    s = research.step_type(step_index)
    return {"plan": "plan", "read": "finding", "synthesize": "synthesis", "synthesize_final": "synthesis"}[s["type"]]


def run_persistent_step(job_id: str, owner: str, region: str) -> bool:
    """Runs (or resumes) exactly one step. Returns False when the job is done.
    Retries the LLM call on a transient failure (rate limit, timeout,
    connection drop) — project_brief.md's own prescribed remedy, previously
    unimplemented (Examiner P1, 2026-08-16). Reuses the same resume_seed
    mechanism built for cross-region standby continuation: on retry, the
    prompt is rebuilt from whatever text was already flushed, so a mid-step
    failure loses at most the in-flight chunk, same as a real kill."""
    step, total_steps, plan_text, partial_output, findings = read_state(job_id)
    if step > total_steps:
        return False

    seq = next_chunk_seq(job_id, step)
    full_text = partial_output

    print(f"\n[STEP {step}/{total_steps}] [{region}] ", end="", flush=True)
    for attempt in range(config.STEP_MAX_RETRIES + 1):
        prompt = research.build_prompt(step, plan_text, findings, resume_seed=full_text)
        buffer = ""
        last_flush = time.monotonic()
        try:
            for delta in llm.step_stream(prompt):
                print(delta, end="", flush=True)
                buffer += delta
                full_text += delta
                now = time.monotonic()
                if now - last_flush >= CHUNK_FLUSH_SECONDS:
                    flush_chunk(job_id, step, seq, buffer, region, owner)
                    seq += 1
                    buffer = ""
                    last_flush = now
            if buffer:
                flush_chunk(job_id, step, seq, buffer, region, owner)
            break
        except Exception as e:
            if buffer:
                flush_chunk(job_id, step, seq, buffer, region, owner)
                seq += 1
            if attempt >= config.STEP_MAX_RETRIES:
                raise
            wait = config.STEP_RETRY_BACKOFF_SECONDS * (2 ** attempt)
            print(
                f"\n[STEP {step}/{total_steps}] [{region}] retrying step {step} "
                f"({type(e).__name__}, attempt {attempt + 2}/{config.STEP_MAX_RETRIES + 1})",
                flush=True,
            )
            time.sleep(wait)
    print()

    finalize_step(job_id, step, total_steps, full_text, region, step_kind_for(step))
    return step < total_steps


def _lease_heartbeat(job_id: str, owner: str, region: str, control_addr: str, stop_event: threading.Event):
    """Renews the lease on a fixed cadence, independent of chunk flushing.
    Without this, a step with long thinking latency before its first token
    can outlast LEASE_TTL_SECONDS and get falsely evicted by a live standby
    even though the primary never died. A SIGKILL takes this thread down
    with the process — no orphaned renewals survive a real kill."""
    while not stop_event.wait(config.LEASE_HEARTBEAT_SECONDS):
        try:
            claim_or_renew_lease(job_id, owner, region, control_addr)
        except Exception:
            pass  # next tick retries; a transient failure here must not crash the worker


def run_persistent(job_id: str, region: str, standby: bool, control_addr: str = None):
    owner = f"{region}:{os.getpid()}"
    if standby:
        print(f"[{region}] standby — polling lease every {config.STANDBY_POLL_SECONDS}s")

    while True:
        claimed = claim_or_renew_lease(job_id, owner, region, control_addr)
        if not claimed:
            time.sleep(config.STANDBY_POLL_SECONDS)
            continue
        if standby:
            print(f"[{region}] lease claimed by {owner} — resuming")

        stop_event = threading.Event()
        heartbeat = threading.Thread(
            target=_lease_heartbeat, args=(job_id, owner, region, control_addr, stop_event), daemon=True
        )
        heartbeat.start()
        try:
            more = run_persistent_step(job_id, owner, region)
        finally:
            stop_event.set()
            heartbeat.join(timeout=1)

        if not more:
            print(f"[{region}] job {job_id} done.")
            return


def run_auto(region: str):
    """F10/F11 continuous demo mode: always a live job for a visitor to
    kill. Starts the control server once (F10's real self-SIGKILL target),
    then loops forever — each time the current demo job finishes, claims
    or creates the next one via state.get_or_create_demo_job, so the
    arena never sits with nothing running (F10's "auto-reset between
    visitors")."""
    control.start_control_server(config.CONTROL_PORT)
    host = control.discover_host()
    control_addr = f"http://{host}:{config.CONTROL_PORT}"
    print(f"[{region}] control server on {control_addr}")

    while True:
        job_id = state.get_or_create_demo_job(research.GOAL, config.TOTAL_STEPS)
        run_persistent(job_id, region, standby=False, control_addr=control_addr)


def run_ephemeral(region: str):
    print(f"\n[{region}] AMNESIA MODE — state in RAM only. Process killed = state gone.")
    print(f"[STEP 1/{config.TOTAL_STEPS}] [{region}] starting research from scratch...\n")
    plan_text = ""
    findings = []
    for step in range(1, config.TOTAL_STEPS + 1):
        prompt = research.build_prompt(step, plan_text, findings, resume_seed="")
        print(f"[STEP {step}/{config.TOTAL_STEPS}] [{region}] ", end="", flush=True)
        full_text = ""
        for delta in llm.step_stream(prompt):
            print(delta, end="", flush=True)
            full_text += delta
        print()
        kind = step_kind_for(step)
        if kind == "plan":
            plan_text = full_text
        else:
            findings.append(full_text)
    print(f"\n[{region}] job done. (nothing persisted — this run leaves no trace)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    parser.add_argument("--job-id")
    parser.add_argument("--goal", default=research.GOAL)
    parser.add_argument("--standby", action="store_true")
    parser.add_argument("--no-memory", action="store_true")
    parser.add_argument("--auto", action="store_true", help="F10/F11: continuous demo mode, see run_auto")
    args = parser.parse_args()

    if args.no_memory:
        run_ephemeral(args.region)
        return

    if args.auto:
        run_auto(args.region)
        return

    job_id = args.job_id
    if job_id is None:
        job_id = create_job(args.goal, config.TOTAL_STEPS)
        print(f"[{args.region}] created job {job_id}")
    run_persistent(job_id, args.region, args.standby)


if __name__ == "__main__":
    main()
