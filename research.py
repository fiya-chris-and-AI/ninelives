"""
Deterministic 20-step research pipeline (F3). Step *types* and their order
are fixed in advance so step boundaries are stable across runs — the LLM
fills in content, never decides how many steps there are. Step 11 lands on
reading the last corpus document (doc_10, write-ahead logging), tuned to
produce a long sentence in flight, matching the demo's kill moment.
"""
import os

GOAL = "What design principle lets a system lose a worker mid-task without losing the task itself?"

CORPUS_DIR = os.path.join(os.path.dirname(__file__), "corpus")


def corpus_docs() -> list[str]:
    return sorted(f for f in os.listdir(CORPUS_DIR) if f.endswith(".md"))


def build_step_plan() -> list[dict]:
    docs = corpus_docs()  # 10 docs, doc_01..doc_10
    plan = [{"index": 1, "type": "plan"}]
    for i, doc in enumerate(docs, start=2):
        plan.append({"index": i, "type": "read", "doc": doc})
    read_end = plan[-1]["index"]  # 11
    remaining = 20 - read_end  # 9 synthesis steps
    for j in range(remaining - 1):
        plan.append({"index": read_end + 1 + j, "type": "synthesize"})
    plan.append({"index": 20, "type": "synthesize_final"})
    return plan


STEP_PLAN = build_step_plan()


def step_type(step_index: int) -> dict:
    """1-indexed step lookup."""
    for s in STEP_PLAN:
        if s["index"] == step_index:
            return s
    raise IndexError(f"no step {step_index} in plan (total {len(STEP_PLAN)})")


def build_prompt(step_index: int, plan_text: str, prior_findings: list[str], resume_seed: str) -> str:
    """Prompt for one step. resume_seed carries persisted partial text when
    resuming mid-step (standby continuation, F2) — empty on a fresh step."""
    s = step_type(step_index)
    resume_clause = (
        f"\n\nYou already began this step and wrote the following before being "
        f"interrupted:\n---\n{resume_seed}\n---\nContinue EXACTLY from the last "
        f"character above. Do not repeat any of it. Do not restart the thought."
        if resume_seed else ""
    )

    if s["type"] == "plan":
        return (
            f"Research goal: {GOAL}\n\n"
            f"You are step 1 of a 20-step research job. Write a short research plan "
            f"(3-5 sentences): what you'll look for and why, given the goal above."
            f"{resume_clause}"
        )

    if s["type"] == "read":
        doc_path = os.path.join(CORPUS_DIR, s["doc"])
        with open(doc_path) as f:
            doc_text = f.read()
        return (
            f"Research goal: {GOAL}\n\nResearch plan so far:\n{plan_text}\n\n"
            f"You are step {step_index} of 20. Read the following source document "
            f"and extract the single most relevant finding for the research goal, "
            f"as one detailed paragraph in flowing prose (not a list). Be specific "
            f"and thorough — explain the mechanism, not just the conclusion.\n\n"
            f"--- SOURCE: {s['doc']} ---\n{doc_text}\n--- END SOURCE ---"
            f"{resume_clause}"
        )

    if s["type"] == "synthesize":
        findings_text = "\n\n".join(f"- {f}" for f in prior_findings)
        return (
            f"Research goal: {GOAL}\n\nFindings gathered so far:\n{findings_text}\n\n"
            f"You are step {step_index} of 20. Write one short paragraph synthesizing "
            f"a connecting pattern across two or more of the findings above that you "
            f"haven't already highlighted."
            f"{resume_clause}"
        )

    if s["type"] == "synthesize_final":
        findings_text = "\n\n".join(f"- {f}" for f in prior_findings)
        return (
            f"Research goal: {GOAL}\n\nAll findings and syntheses gathered:\n{findings_text}\n\n"
            f"You are the final step, 20 of 20. Write a concise closing synthesis "
            f"(4-6 sentences) that directly answers the research goal."
            f"{resume_clause}"
        )

    raise ValueError(f"unknown step type: {s['type']}")
