import json
from pathlib import Path

PANEL_SCORE = (
    "Panel score: per reviewer 100 × Σ weight of passed checklist items / Σ weight of answered items "
    "(yes/no only); unclear and not reported lower the coverage, not the score. Paper score = mean of "
    "reviewers. Computed in code; red flags are answers matching an item's red-flag rule."
)


def pct(value):
    return f"{round(100 * value)}%"


def panel_lines(i, paper, row, review):
    reason = f" ({review['text_reason']})" if review["text_reason"] else ""
    lines = [
        f"## {i}. {paper['title']}",
        "",
        (
            f"ID: {paper['id']} · year: {paper['year']} · score: **{row['score']}/100** · "
            f"coverage: {pct(review['coverage'])}"
        ),
        f"DOI: {paper['doi'] or 'not available'}",
        f"Text: {review['text_source']}{reason}",
        "",
        "### Peer review",
        "",
        f"Editor: **{review['editor']['verdict']}**. {review['editor']['reason']}",
        "",
    ]
    for d in review["editor"]["disagreements"]:
        lines.append(f"- Disagreement on {d['item']} ({', '.join(d['reviewers'])}): {d['note']}")
    for flag in review["red_flags"]:
        who = ", ".join(r["reviewer"] for r in flag["raised_by"])
        lines.append(f"- Red flag: {flag['text']} [{flag['source'] or 'no source tag'}], raised by {who}")
    for key, r in review["reviews"].items():
        lines += [
            "",
            (
                f"#### {r['name']} ({key} v{r['version']}): {r['verdict']} · score {r['score']} · "
                f"coverage {pct(r['coverage'])}"
            ),
            "",
            r["summary"],
            "",
        ]
        for a in r["answers"]:
            quote = ""
            if a["quote"]:
                quote = f" — “{a['quote']}”" + (f" ({a['section']})" if a["section"] else "")
            lines.append(f"- {a['key']}: {a['answer'].replace('_', ' ')}{quote}")
    lines += ["", f"Found by: {', '.join(paper.get('sources') or []) or 'not recorded'}", ""]
    return lines


def unranked_reason(state, pid):
    review = state.get("review")
    if review is not None and pid in review:
        entry = review[pid]
        if entry["editor"]["verdict"] == "exclude":
            return "Editor: exclude"
        return "No checklist item answered" if entry["score"] is None else "Eligible but below top 10 cutoff"
    decision = state["decisions"].get(pid)
    reason = decision["review"]["verdict"] if decision else state["screens"][pid]["reason"]
    return "Eligible but below top 10 cutoff" if decision and reason == "include" else reason


def write_report(state, directory, manifest):
    directory = Path(directory)
    papers = {p["id"]: p for p in state["papers"]}
    review = state.get("review")
    scoring = (
        [PANEL_SCORE]
        if review is not None
        else [
            "Score v1: 100 × (0.4 relevance + 0.3 methods detail + 0.3 claim support) / 4.",
            "Each component: 0–4. Agreement uses component-wise minima; disagreement uses adjudicator scores.",
        ]
    )
    lines = [
        "# Research Agent — milestone 1",
        "",
        f"Topic: {state['contract']['topic']}",
        "",
        *(
            [f"Field: {field['name']} · version {field['version']}", ""]
            if (field := (state["contract"].get("domain") or {}).get("field"))
            else []
        ),
        f"Mode: **{state['contract']['mode']}** · scope: "
        + ("**FULL TEXT WHERE AVAILABLE**" if review is not None else "**ABSTRACT ONLY**"),
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
        *scoring,
        "",
        *(
            [
                "**Partial search.** Skipped sources: "
                + "; ".join(f"{w['source']} ({w['reason']})" for w in warnings)
                + ". Results may be missing papers from these sources.",
                "",
            ]
            if (warnings := state.get("search_warnings"))
            else []
        ),
        "Search is bounded to one page per query. Abstracts cannot establish full methodological quality.",
        "",
        "## Query plan",
        "",
        *[f"- {q}" for q in state["plan"]["queries"]],
        *[
            f"- {source} (from keywords): {q}"
            for source, q in (state["plan"].get("source_queries") or {}).items()
        ],
        "",
    ]
    for i, row in enumerate(state["ranking"], 1):
        p, d = papers[row["paper_id"]], row["decision"]
        if review is not None:
            lines += panel_lines(i, p, row, review[p["id"]])
            continue
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
            f"Found by: {', '.join(p.get('sources') or []) or 'not recorded'}",
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
        lines += [f"- {pid}: {unranked_reason(state, pid)}"]
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
