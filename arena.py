"""
The arena: FastAPI orchestration only — business logic lives in
monitor.py (F7 brain monitor + F10 worker panes/lease signal), recall.py
(F8), state.py (job/lease reads), and each worker's own control.py (F10
kill target).

Three background threads each read one changefeed once (memory_events,
output_chunks, lease) and fan events out to every connected SSE client,
tagged by event type — one shared feed, not one changefeed connection
per browser tab, and not one SSE connection per signal.

Run: .venv/bin/uvicorn arena:app --reload --port 8000
"""
import asyncio
import json
import queue
import threading
import time
import urllib.request
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

import config
import monitor
import recall as recall_module
import state

_subscribers: set[queue.Queue] = set()
_subscribers_lock = threading.Lock()


def _broadcast(event_type: str, stream_fn):
    for event in stream_fn():
        with _subscribers_lock:
            subs = list(_subscribers)
        for q in subs:
            q.put((event_type, event))


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_broadcast, args=("memory_write", monitor.stream_memory_writes), daemon=True).start()
    threading.Thread(target=_broadcast, args=("output_chunk", monitor.stream_output_chunks), daemon=True).start()
    threading.Thread(target=_broadcast, args=("lease", monitor.stream_lease), daemon=True).start()
    yield


app = FastAPI(title="ninelives arena", lifespan=lifespan)

_last_kill_ts = 0.0
_kill_lock = threading.Lock()


class RecallRequest(BaseModel):
    question: str


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/api/status")
def api_status():
    job_id = state.get_demo_job_id()
    if job_id is None:
        return {"job_id": None, "step": None, "total_steps": None, "lease": None}
    return state.get_job_snapshot(job_id)


@app.get("/api/monitor/stream")
async def monitor_stream(request: Request):
    async def event_generator():
        q: queue.Queue = queue.Queue()
        with _subscribers_lock:
            _subscribers.add(q)
        try:
            while True:
                if await request.is_disconnected():
                    break
                loop = asyncio.get_event_loop()
                try:
                    event_type, payload = await loop.run_in_executor(None, q.get, True, 1.0)
                except queue.Empty:
                    continue
                yield {"event": event_type, "data": json.dumps(payload)}
        finally:
            with _subscribers_lock:
                _subscribers.discard(q)

    return EventSourceResponse(event_generator())


@app.post("/api/recall")
def api_recall(body: RecallRequest):
    return recall_module.recall(body.question)


@app.post("/api/kill")
def api_kill():
    """F10: SIGKILLs whichever worker currently holds the demo job's
    lease. Rate-limited (also doubles as "disabled while a resume is in
    flight" — a resume completes well within the cooldown per F2's <=5s
    bar). A connection error/reset from the control call is the expected
    success signal: the process died mid-response."""
    global _last_kill_ts
    with _kill_lock:
        now = time.monotonic()
        elapsed = now - _last_kill_ts
        if elapsed < config.KILL_COOLDOWN_SECONDS:
            retry_after = round(config.KILL_COOLDOWN_SECONDS - elapsed, 1)
            return JSONResponse({"ok": False, "reason": "cooldown", "retry_after": retry_after}, status_code=429)
        _last_kill_ts = now

    job_id = state.get_demo_job_id()
    if job_id is None:
        return JSONResponse({"ok": False, "reason": "no active job"}, status_code=409)

    lease = state.get_active_lease(job_id)
    if lease is None or not lease.get("control_addr"):
        return JSONResponse({"ok": False, "reason": "no active worker"}, status_code=409)

    region = lease["region"]
    req = urllib.request.Request(
        f"{lease['control_addr']}/kill",
        method="POST",
        headers={"X-Control-Secret": config.CONTROL_SHARED_SECRET},
    )
    try:
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass  # expected: the worker died before it could finish responding

    return {"ok": True, "killed_region": region}
