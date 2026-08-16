"""
F8: episodic memory + recall. Vector-searches memory_events for a
natural-language question; the answer is the top-ranked row's content
verbatim, not a model-resynthesized paraphrase. Provenance rows come
straight from SQL — the model can be wrong, the rows cannot
(project_brief.md AI Capability Notes).

Live-measured tradeoff: an LLM-synthesized answer over the retrieved rows
was tried first and consistently cost 3.2-4.6s (5 samples against the
real Anthropic API, Claude Opus 5, effort=low) — thinking-token latency
the brief's own model guidance forbids disabling — which misses F8's
<3s acceptance bar. Quoting the top row directly is embed+search only
(<1s, profiled) and is still a grounded, on-topic answer: findings and
seed memories are already written as flowing prose (research.py's "one
detailed paragraph", seed_memories.py's curated sentences), curated for
exactly this recall query.
"""
import config
import db
import embeddings


def recall(question: str, top_k: int = None) -> dict:
    """Returns {"answer": str, "provenance": [row, ...]}. The Beat-4
    acceptance bar is >=3 provenance rows in <3s."""
    top_k = top_k if top_k is not None else config.RECALL_TOP_K
    query_vec = embeddings.embed(question)

    def txn(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, job_id, ts, region, step, kind, content, source, curated, "
                "embedding <-> %s AS distance "
                "FROM memory_events ORDER BY distance ASC LIMIT %s",
                (str(query_vec), top_k),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    rows = db.run_txn(txn)
    provenance = [_serialize(row) for row in rows]

    if not provenance:
        return {"answer": "no episodes yet — kill me first", "provenance": []}

    return {"answer": provenance[0]["content"], "provenance": provenance}


def _serialize(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "job_id": str(row["job_id"]),
        "ts": row["ts"].isoformat(),
        "region": row["region"],
        "step": row["step"],
        "kind": row["kind"],
        "content": row["content"],
        "source": row.get("source"),
        "curated": row.get("curated", False),
        "distance": float(row["distance"]),
    }
