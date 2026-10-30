"""ProofCrew orchestration.

The design rule, end to end: **no agent grades its own homework.**

  1. PLAN        Nemotron 3 Ultra splits the task into two complementary,
                 non-overlapping parts and a web search query.
  2. WORK        Two Nemotron 3 Super workers execute the parts in parallel.
                 Worker B grounds its part with a Tavily search when a Tavily
                 key is configured; if not, its receipt records
                 ``grounded: false`` — the crew never fakes a research call.
  3. SCREEN      Nemotron 3 Nano — which produced none of the work — screens
                 both outputs for errors, omissions, and incoherence.
  4. CROSS-VERIFY Each Super worker verifies the *other* worker's output.
                 Neither ever sees a verify prompt about its own work.
  5. ADJUDICATE  Only if the cross-verification disagrees does Ultra return
                 to produce the final, corrected deliverable. On agreement
                 the two parts are assembled deterministically — no extra
                 model call, no silent edits.

Every stage appends a hash-chained receipt (see receipts.py).
"""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .config import Config
from .receipts import ReceiptChain
from .tavily import format_results
from .transport import ChatTransport

PLAN_SYSTEM = """You are the planner in ProofCrew, a crew where no agent grades its own homework.
Split the user's task into two complementary, non-overlapping parts that together cover the whole task: part A (research-light, structural, or first half) and part B (the part that benefits most from current web facts).
Also write one web search query that would ground part B in current facts.
Respond with JSON only, no prose around it:
{"plan": "<short plan>", "worker_a_task": "<exact assignment for worker A>", "worker_b_task": "<exact assignment for worker B>", "search_query": "<query>"}"""

WORKER_SYSTEM = """You are a worker in ProofCrew. Complete exactly the part assigned to you — thoroughly, concretely, and in a form that can stand as one section of a final deliverable.
Your output will be screened by an independent model and cross-verified by a peer worker. Do not review or grade anything; just do your part well."""

SCREEN_SYSTEM = """You are an independent screener in ProofCrew. You produced none of the work below; your only job is to screen it.
Flag factual errors, missing pieces, unsupported claims, and incoherence in each worker's output.
Respond with JSON only:
{"worker_a": {"pass": true, "notes": "<short>"}, "worker_b": {"pass": true, "notes": "<short>"}, "flags": ["<any cross-cutting concern>"]}"""

VERIFY_SYSTEM = """You are cross-verifying a peer worker's output in ProofCrew. You did not write this output, and you must never verify your own work — that is the crew's founding rule.
Check the output against the original task: factual errors, omissions, contradictions, unsupported claims.
Respond with JSON only:
{"verdict": "agree" or "disagree", "issues": ["<each concrete problem, or empty if you agree>"]}
Say "agree" only if you would stand behind this output as correct and complete for its assigned part."""

ADJUDICATE_SYSTEM = """You are the adjudicator in ProofCrew. Two workers produced parts of a task and their cross-verification disagreed, so the decision escalates to you — and only in this case.
Using the original task, both outputs, and both peer reviews, produce the final corrected deliverable for the whole task, resolving every disputed point. Output only the deliverable."""


def extract_json(text: str) -> dict | None:
    """Best-effort extraction of the first JSON object in a model response."""
    if not text:
        return None
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


def verdict_of(review: dict | None) -> str:
    """Normalize a cross-verification review to 'agree' / 'disagree'.

    Anything that is not an explicit 'agree' counts as disagreement: an
    unparseable review escalates to the adjudicator rather than silently
    passing. Conservative by design."""
    if not review:
        return "disagree"
    return "agree" if str(review.get("verdict", "")).strip().lower() == "agree" else "disagree"


def needs_adjudication(review_a_on_b: dict | None, review_b_on_a: dict | None) -> bool:
    """The adjudicator is called ONLY when cross-verification disagrees."""
    return verdict_of(review_a_on_b) != "agree" or verdict_of(review_b_on_a) != "agree"


@dataclass
class RunResult:
    task: str
    deliverable: str
    chain: ReceiptChain
    adjudicated: bool
    grounded_worker_b: bool


def run_crew(
    task: str,
    transport: ChatTransport,
    config: Config,
    tavily_client=None,
) -> RunResult:
    chain = ReceiptChain()

    # 1 — PLAN (Ultra)
    plan_raw = transport.complete(config.planner_model, PLAN_SYSTEM, task)
    plan = extract_json(plan_raw) or {}
    plan_text = plan.get("plan") or plan_raw
    a_task = plan.get("worker_a_task") or task
    b_task = plan.get("worker_b_task") or task
    search_query = plan.get("search_query") or task
    chain.append(
        "planner",
        "plan",
        {
            "model": config.planner_model,
            "task": task,
            "plan": plan_text,
            "worker_a_task": a_task,
            "worker_b_task": b_task,
            "search_query": search_query,
        },
    )

    # 2 — WORK (two Supers in parallel; B grounded via Tavily when keyed)
    grounded = tavily_client is not None
    research = ""
    if grounded:
        research = format_results(tavily_client.search(search_query))

    def do_work(subtask: str, extra: str) -> str:
        user = subtask
        if extra:
            user += "\n\nWeb research gathered for you via Tavily — use it and cite the URLs where you rely on a fact:\n" + extra
        return transport.complete(config.worker_model, WORKER_SYSTEM, user)

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_a = pool.submit(do_work, a_task, "")
        fut_b = pool.submit(do_work, b_task, research if grounded else "")
        out_a = fut_a.result()
        out_b = fut_b.result()

    chain.append(
        "worker_a",
        "work",
        {"model": config.worker_model, "grounded": False, "output": out_a},
    )
    chain.append(
        "worker_b",
        "work",
        {"model": config.worker_model, "grounded": grounded, "output": out_b},
    )

    # 3 — SCREEN (Nano; it produced none of the work)
    screen_raw = transport.complete(
        config.screener_model,
        SCREEN_SYSTEM,
        f"Original task:\n{task}\n\nWorker A output:\n{out_a}\n\nWorker B output:\n{out_b}",
    )
    chain.append(
        "screener",
        "screen",
        {
            "model": config.screener_model,
            "screen": extract_json(screen_raw) or {"raw": screen_raw},
        },
    )

    # 4 — CROSS-VERIFY (each Super verifies the OTHER worker's output)
    review_a_raw = transport.complete(
        config.worker_model,
        VERIFY_SYSTEM,
        f"Original task:\n{task}\n\nThe peer worker's assigned part:\n{b_task}\n\nThe peer worker's output:\n{out_b}",
    )
    review_b_raw = transport.complete(
        config.worker_model,
        VERIFY_SYSTEM,
        f"Original task:\n{task}\n\nThe peer worker's assigned part:\n{a_task}\n\nThe peer worker's output:\n{out_a}",
    )
    review_a = extract_json(review_a_raw) or {
        "verdict": "disagree",
        "issues": ["review was not structured JSON; escalated out of caution"],
        "raw": review_a_raw,
    }
    review_b = extract_json(review_b_raw) or {
        "verdict": "disagree",
        "issues": ["review was not structured JSON; escalated out of caution"],
        "raw": review_b_raw,
    }
    chain.append(
        "worker_a",
        "verify",
        {
            "model": config.worker_model,
            "target": "worker_b",
            "verdict": verdict_of(review_a),
            "issues": review_a.get("issues", []),
        },
    )
    chain.append(
        "worker_b",
        "verify",
        {
            "model": config.worker_model,
            "target": "worker_a",
            "verdict": verdict_of(review_b),
            "issues": review_b.get("issues", []),
        },
    )

    # 5 — ADJUDICATE (Ultra) only on disagreement; else assemble as-is.
    adjudicated = needs_adjudication(review_a, review_b)
    if adjudicated:
        deliverable = transport.complete(
            config.planner_model,
            ADJUDICATE_SYSTEM,
            (
                f"Original task:\n{task}\n\nWorker A output:\n{out_a}\n\nWorker B output:\n{out_b}\n\n"
                f"Worker A's review of B: {json.dumps(review_a)}\n\nWorker B's review of A: {json.dumps(review_b)}"
            ),
        )
        chain.append(
            "planner",
            "adjudication",
            {
                "model": config.planner_model,
                "reason": "cross-verification disagreement",
                "output": deliverable,
            },
        )
    else:
        deliverable = out_a.rstrip() + "\n\n" + out_b.rstrip() + "\n"
        chain.append(
            "crew",
            "assembly",
            {
                "adjudication_skipped": True,
                "reason": "cross-verification agreement — parts assembled without alteration",
            },
        )

    chain.append(
        "crew",
        "final",
        {
            "deliverable_sha256": hashlib.sha256(deliverable.encode("utf-8")).hexdigest(),
            "adjudicated": adjudicated,
            "grounded_worker_b": grounded,
        },
    )
    return RunResult(
        task=task,
        deliverable=deliverable,
        chain=chain,
        adjudicated=adjudicated,
        grounded_worker_b=grounded,
    )
