import itertools
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .agents import validate_evidence
from .connectors import deduplicate
from .criteria import criterion_keys, decide_llm, screen_payload
from .schemas import CriteriaScreen, Decision, Evidence, Paper, Plan, Review, Screen

NO_ABSTRACT = "No abstract available; retained in audit, unranked."


def plan_payload(contract):
    """Legacy runs send exactly today's payload; a field adds its criteria and year range."""
    payload = {k: v for k, v in contract.items() if k != "domain"}
    if contract.get("domain"):
        payload["criteria"] = contract["domain"]["criteria"]
        payload["years"] = contract["domain"]["years"]
    return payload


class State(TypedDict, total=False):
    contract: dict
    plan: dict
    discovered: list[dict]
    papers: list[dict]
    screens: dict
    evidence: dict
    reviews_a: dict
    reviews_b: dict
    decisions: dict
    ranking: list[dict]


def disagreement(a, b):
    return a["verdict"] != b["verdict"] or any(
        abs(a[k] - b[k]) >= 2 for k in ("relevance", "methods", "support")
    )


def score(review):
    # Version m1.1: weights fixed before evaluating; no citation/popularity feature.
    return round(100 * (0.4 * review["relevance"] + 0.3 * review["methods"] + 0.3 * review["support"]) / 4, 2)


def build_graph(connector, evaluator, checkpointer=None, interrupt_after=None, observer=None, jev=None):
    def plan(s):
        return {"plan": evaluator.ask("plan", Plan, plan_payload(s["contract"])).model_dump()}

    def discover(s):
        papers = []
        for query in s["plan"]["queries"]:
            papers.extend(connector.search(query, s["contract"]["max_papers"]))
        return {"discovered": [p.model_dump() for p in papers]}

    def normalize(s):
        papers = deduplicate([Paper.model_validate(p) for p in s["discovered"]])
        # Bound expensive model work, deterministically in query/rank discovery order.
        order = {p["id"]: i for i, p in reversed(list(enumerate(s["discovered"])))}
        papers.sort(key=lambda p: min(order.get(src.record_id, 10**9) for src in p.provenance))
        return {"papers": [p.model_dump() for p in papers[: s["contract"]["max_papers"]]]}

    def screen_topic(topic, paper):
        # Tier 1 (optional): Jev decides only when confident; otherwise the LLM sees the same
        # payload as without Jev (evidence, never Jev's conclusion).
        verdict = jev.screen(topic, paper) if jev else None
        if verdict and verdict["decision"] != "escalate":
            entry = {
                "decision": verdict["decision"],
                "reason": "Jev: "
                + ", ".join(f"{q} p={p:.2f}" for q, p in verdict["probabilities"].items())
                + f" ({verdict['model_version']})",
                "tier": "jev",
            }
        else:
            entry = {
                **evaluator.ask("screen", Screen, {"topic": topic, "paper": paper}).model_dump(),
                "tier": "llm",
            }
        if verdict:
            entry["jev"] = verdict
        entry["decided_by"] = "topic_match" if entry["decision"] == "exclude" else None
        entry["criteria"] = {
            q: {"jev_p": p, "llm": None, "quote": None}
            for q, p in (verdict or {}).get("probabilities", {}).items()
        }
        return entry

    def screen_criteria(domain, paper):
        cells = {k: {"jev_p": None, "llm": None, "quote": None} for k in criterion_keys(domain["criteria"])}
        verdict = jev.screen_criteria(paper, domain) if jev else None
        for key, p in (verdict or {}).get("probabilities", {}).items():
            cells[key]["jev_p"] = p
        if verdict and verdict["decision"] != "escalate":
            dropped = f"; dropped by {verdict['decided_by']}" if verdict["decided_by"] else ""
            entry = {
                "decision": verdict["decision"],
                "reason": "Jev: "
                + ", ".join(f"{k} p={p:.2f}" for k, p in verdict["probabilities"].items())
                + f" ({verdict['model_version']}){dropped}",
                "tier": "jev",
                "decided_by": verdict["decided_by"],
            }
        else:
            answer = evaluator.ask("screen_criteria", CriteriaScreen, screen_payload(domain, paper))
            for a in answer.answers:
                cells[a.key]["llm"], cells[a.key]["quote"] = a.answer, a.quote or None
            decision, decided_by = decide_llm({a.key: a.answer for a in answer.answers}, domain["criteria"])
            entry = {"decision": decision, "reason": answer.reason, "tier": "llm", "decided_by": decided_by}
        entry["criteria"] = cells
        if verdict:
            entry["jev"] = verdict
        return entry

    def screen(s):
        topic, domain, results = s["contract"]["topic"], s["contract"].get("domain"), {}
        for paper in s["papers"]:
            if not paper["abstract"]:
                keys = criterion_keys(domain["criteria"]) if domain else []
                results[paper["id"]] = {
                    **Screen(decision="uncertain", reason=NO_ABSTRACT).model_dump(),
                    "tier": "rule",
                    "decided_by": None,
                    "criteria": {k: {"jev_p": None, "llm": None, "quote": None} for k in keys},
                }
            elif domain:
                results[paper["id"]] = screen_criteria(domain, paper)
            else:
                results[paper["id"]] = screen_topic(topic, paper)
        return {"screens": results}

    def extract(s):
        results = {}
        for paper in s["papers"]:
            if s["screens"][paper["id"]]["decision"] != "exclude" and paper["abstract"]:
                evidence = evaluator.ask("extract", Evidence, {"paper": paper})
                validate_evidence(evidence, paper["abstract"])
                results[paper["id"]] = evidence.model_dump()
        return {"evidence": results}

    def reviewer(role, field):
        def run(s):
            # No sibling review enters either prompt. Branches execute concurrently.
            return {
                field: {
                    p["id"]: evaluator.ask(
                        role,
                        Review,
                        {"topic": s["contract"]["topic"], "paper": p, "evidence": s["evidence"][p["id"]]},
                    ).model_dump()
                    for p in s["papers"]
                    if p["id"] in s["evidence"]
                }
            }

        return run

    def adjudicate(s):
        results = {}
        for p in s["papers"]:
            pid = p["id"]
            if pid not in s["evidence"]:
                continue
            a, b = s["reviews_a"][pid], s["reviews_b"][pid]
            if disagreement(a, b):
                decision = evaluator.ask(
                    "adjudicate",
                    Decision,
                    {
                        "topic": s["contract"]["topic"],
                        "paper": p,
                        "evidence": s["evidence"][pid],
                        "reviews": [a, b],
                    },
                ).model_dump()
                decision["adjudicated"] = True
            else:
                # Conservatively combine scores and preserve both interpretations.
                merged = dict(a)
                for key in ("relevance", "methods", "support"):
                    merged[key] = min(a[key], b[key])
                for key in ("strengths", "weaknesses", "takeaways"):
                    merged[key] = list(dict.fromkeys(a[key] + b[key]))
                merged["assessment"] = a["assessment"] + " | Critic: " + b["assessment"]
                decision = {
                    "review": merged,
                    "reason": "Same verdict; all score gaps <2. Conservative minima.",
                    "adjudicated": False,
                }
            results[pid] = decision
        return {"decisions": results}

    def rank(s):
        rows = [
            {"paper_id": pid, "score": score(d["review"]), "decision": d}
            for pid, d in s["decisions"].items()
            if d["review"]["verdict"] == "include"
        ]
        return {"ranking": sorted(rows, key=lambda r: (-r["score"], r["paper_id"]))[:10]}

    def observed(name, node):
        def invoke(state):
            observer(name, "running")
            try:
                result = node(state)
            except Exception:
                observer(name, "failed")
                raise
            observer(name, "completed")
            return result

        return invoke

    graph = StateGraph(State)
    for name, node in [
        ("plan", plan),
        ("discover", discover),
        ("normalize", normalize),
        ("screen", screen),
        ("extract", extract),
        ("review_a", reviewer("review_a", "reviews_a")),
        ("review_b", reviewer("review_b", "reviews_b")),
        ("adjudicate", adjudicate),
        ("rank", rank),
    ]:
        graph.add_node(name, observed(name, node) if observer else node)
    chain = [START, "plan", "discover", "normalize", "screen", "extract"]
    for a, b in itertools.pairwise(chain):
        graph.add_edge(a, b)
    graph.add_edge("extract", "review_a")
    graph.add_edge("extract", "review_b")
    graph.add_edge(["review_a", "review_b"], "adjudicate")
    graph.add_edge("adjudicate", "rank")
    graph.add_edge("rank", END)
    return graph.compile(checkpointer=checkpointer, interrupt_after=interrupt_after or [])
