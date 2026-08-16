"""
The arena: FastAPI orchestration only — business logic lives in monitor.py
(F7) and recall.py (F8). F10's worker panes + KILL AGENT endpoint are not
built yet (M3, pending go-ahead); this file currently serves the brain
monitor panel and the recall query.

One background thread reads monitor.stream_memory_writes() once and fans
each event out to every connected SSE client — a single shared feed, not
one changefeed connection per browser tab.

Run: .venv/bin/uvicorn arena:app --reload --port 8000
"""
import asyncio
import json
import queue
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

import monitor
import recall as recall_module

_subscribers: set[queue.Queue] = set()
_subscribers_lock = threading.Lock()


def _broadcast_loop():
    for event in monitor.stream_memory_writes():
        with _subscribers_lock:
            subs = list(_subscribers)
        for q in subs:
            q.put(event)


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_broadcast_loop, daemon=True).start()
    yield


app = FastAPI(title="ninelives arena", lifespan=lifespan)


class RecallRequest(BaseModel):
    question: str


@app.get("/")
def index():
    return FileResponse("static/index.html")


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
                    event = await loop.run_in_executor(None, q.get, True, 1.0)
                except queue.Empty:
                    continue
                yield {"event": "memory_write", "data": json.dumps(event)}
        finally:
            with _subscribers_lock:
                _subscribers.discard(q)

    return EventSourceResponse(event_generator())


@app.post("/api/recall")
def api_recall(body: RecallRequest):
    return recall_module.recall(body.question)
