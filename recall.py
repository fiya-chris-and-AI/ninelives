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
import re

import config
import db
import embeddings

# CD1-2 (2026-08-17, creative_prompts_round_1.md): the top row's content
# runs up to ~350 words, but Beat 4 gives the answer ~25s of screen time
# and project_brief.md Section 5's own legibility bar is "readable in a
# 1080p recording at 2x speed" — a 350-word wall of text fails that
# regardless of research quality. Cut on a real sentence boundary, never
# mid-word/mid-clause; the full text stays available (see api_recall's
# "answer_full"), this only changes what's visible on first render.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _lead_excerpt(text: str, target_words: int = 60, max_sentences: int = 3) -> str:
    """First 2-3 sentences, capped near target_words, always a clean
    sentence-boundary cut. Always keeps at least one full sentence even
    if that sentence alone exceeds target_words."""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s]
    if not sentences:
        return text.strip()

    excerpt_sentences = [sentences[0]]
    word_count = len(sentences[0].split())
    for sentence in sentences[1:]:
        if len(excerpt_sentences) >= max_sentences or word_count >= target_words:
            break
        excerpt_sentences.append(sentence)
        word_count += len(sentence.split())

    return " ".join(excerpt_sentences)


def recall(question: str, top_k: int = None) -> dict:
    """Returns {"answer": str, "answer_full": str, "provenance": [row, ...]}.
    "answer" is a sentence-boundary excerpt sized for Beat 4's screen time
    (CD1-2); "answer_full" is the complete, undiscarded research content.
    The Beat-4 acceptance bar is >=3 provenance rows in <3s."""
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
        return {"answer": "no episodes yet — kill me first", "answer_full": "", "provenance": []}

    full_answer = provenance[0]["content"]
    return {"answer": _lead_excerpt(full_answer), "answer_full": full_answer, "provenance": provenance}


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
