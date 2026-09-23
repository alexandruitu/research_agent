import json
from pathlib import Path


def write_report(state, directory, manifest):
    directory = Path(directory)
    papers = {p["id"]: p for p in state["papers"]}
    lines = [
        "# Research Agent — milestone 1",
        "",
        f"Topic: {state['contract']['topic']}",
        "",
        f"Mode: **{state['contract']['mode']}** · scope: **ABSTRACT ONLY**",
        "",
        "DEMO: all papers and evaluations are synthetic."
        if state["contract"]["mode"] == "demo"
        else "Live retrieval and model evaluation. Scores are provisional abstract-level triage, not validated scientific quality.",
        "",
        (
            f"Retrieved {len(state['discovered'])} records; considered {len(papers)} unique candidates; "
            f"ranked {len(state['ranking'])} (at most 10; never padded)."
        ),
        "",
        "Score v1: 100 × (0.4 relevance + 0.3 methods detail + 0.3 claim support) / 4.",
        "Each component: 0–4. Agreement uses component-wise minima; disagreement uses adjudicator scores.",
        "",
        "Search is bounded to one page per query. Abstracts cannot establish full methodological quality.",
        "",
        "## Query plan",
        "",
        *[f"- {q}" for q in state["plan"]["queries"]],
        "",
    ]
    for i, row in enumerate(state["ranking"], 1):
        p, d = papers[row["paper_id"]], row["decision"]
        r = d["review"]
        lines += [
            f"## {i}. {p['title']}",
            "",
            f"ID: {p['id']} · year: {p['year']} · score: **{row['score']}/100**",
            f"DOI: {p['doi'] or 'not available'}",
            "",
            f"Components: relevance {r['relevance']}; methods detail {r['methods']}; support {r['support']}.",
            "",
            "**Strengths**",
            "",
            *[f"- {x}" for x in r["strengths"]],
            "",
            "**Qualitative assessment**",
            "",
            r["assessment"],
            "",
            "**Limitations**",
            "",
            *[f"- {x}" for x in r["weaknesses"]],
            "",
            "**Main takeaways**",
            "",
            *[f"- {x}" for x in r["takeaways"]],
            "",
            f"Adjudicated: {d['adjudicated']}. {d['reason']}",
            "",
            "**Evidence and provenance**",
            "",
        ]
        for c in state["evidence"][p["id"]]["claims"]:
            lines += [f"- {c['statement']} — exact abstract span: “{c['quote']}”"]
        for src in p["provenance"]:
            lines += [
                f"- {src['url']} · query: {src['query']} · retrieved: {src['retrieved_at']} · raw SHA-256: `{src['raw_sha256']}`"
            ]
        lines += [""]
    lines += ["## Unranked candidates", ""]
    ranked = {r["paper_id"] for r in state["ranking"]}
    for pid in sorted(papers.keys() - ranked):
        decision = state["decisions"].get(pid)
        reason = decision["review"]["verdict"] if decision else state["screens"][pid]["reason"]
        if decision and reason == "include":
            reason = "Eligible but below top 10 cutoff"
        lines += [f"- {pid}: {reason}"]
    lines += [
        "",
        "## Audit",
        "",
        (
            "Full state, independent reviews and decisions: report.json. "
            "Raw source payloads and model prompts/outputs: research.sqlite. Resume state: checkpoints.sqlite."
        ),
        "",
        "Models: " + json.dumps(manifest["models"], ensure_ascii=False),
        "",
    ]
    (directory / "report.md").write_text("\n".join(lines))
    (directory / "report.json").write_text(
        json.dumps({"manifest": manifest, "state": state}, indent=2, ensure_ascii=False)
    )
