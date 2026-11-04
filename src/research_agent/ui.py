"""Local research dashboard. Start with research-ui or python -m research_agent.ui_launcher."""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from research_agent.jobs import PROJECT, launch, list_runs, new_directory, root_directory, status
from research_agent.runner import STAGES, atomic_json, read_json
from research_agent.schemas import Contract

st.set_page_config(
    page_title="Research Studio", page_icon="🔬", layout="wide", initial_sidebar_state="expanded"
)
load_dotenv(PROJECT / ".env")
ROOT = root_directory()
DEFAULTS = read_json(ROOT / "ui-settings.json", {})

st.markdown(
    """<style>
.stApp {background: #f6f8f7;}
[data-testid="stSidebar"] {background: #edf2ef; border-right: 1px solid #dce5df;}
h1, h2, h3 {color: #183c31; letter-spacing: -.03em;}
[data-testid="stMetric"] {background: white; border: 1px solid #dce5df; border-radius: 12px; padding: 16px;}
.stButton>button[kind="primary"], .stFormSubmitButton>button[kind="primary"] {background:#20644d; border-color:#20644d;}
[data-testid="stMainBlockContainer"] {padding-top: 4.5rem; max-width: 1500px;}
[data-testid="stCaptionContainer"] {color: #587066;}
</style>""",
    unsafe_allow_html=True,
)

if st.session_state.pop("clear_credentials", False):
    for key in ("credential_openai", "credential_anthropic"):
        st.session_state.pop(key, None)
if "active_run" not in st.session_state:
    example = PROJECT / "examples/demo"
    st.session_state.active_run = str(example) if (example / "report.json").exists() else None

with st.sidebar:
    st.markdown("## 🔬 Research Studio")
    st.caption("From question to verifiable evidence")
    if st.button("＋ New research", type="primary", use_container_width=True):
        st.session_state.active_run = None
        st.rerun()
    st.divider()
    st.markdown("**Research library**")
    runs = list_runs(ROOT)
    labels = {
        str(p): ("DEMO · " if m["contract"]["mode"] == "demo" else "LIVE · ")
        + m["contract"]["topic"][:65]
        + " · "
        + p.name
        for p, m in runs
    }
    if runs:
        choice = st.selectbox(
            "Saved research", list(labels), format_func=lambda p: labels[p], label_visibility="collapsed"
        )
        if st.button("Open research", use_container_width=True):
            st.session_state.active_run = choice
            st.rerun()
    else:
        st.caption("New research will appear here.")
    st.divider()
    st.caption("V1 · Abstract-level analysis")
    st.caption("Europe PMC in live mode. The demo uses synthetic data.")
    st.caption("Local storage · SQLite · checkpoints")


def configuration():
    st.caption("RESEARCH SPACE / SETUP")
    st.title("What do you want to find out?")
    st.write(
        "Set the topic and the reviewers. Watch the papers found turn into a reasoned ranking."
    )
    mode_label = st.radio(
        "Mode", ["Demo · no API keys", "Live · real sources and models"], horizontal=True
    )
    live = mode_label.startswith("Live")
    if not live:
        st.info(
            "The demo tests the whole flow with synthetic papers and reviews. It does not produce scientific conclusions."
        )
    with st.form("configuration"):
        topic = st.text_area(
            "Research topic",
            value=DEFAULTS.get("topic", "retrieval augmented generation clinical question answering"),
            max_chars=500,
            height=90,
        )
        left, right = st.columns(2)
        maximum = left.slider("Candidates to review", 1, 30, int(DEFAULTS.get("max_papers", 12)))
        pause = right.selectbox(
            "Stopping point", ["No pause", "After search", "After evidence extraction", "After adjudication"]
        )
        st.caption(
            "At most 10 results in the ranking. A larger batch means more calls and a higher cost in live mode."
        )
        models, credentials = {}, {}
        if live:
            st.subheader("Models and access")
            st.caption(
                "Model format: provider:model-name. For example, anthropic:ID or openai:ID. Enter a model available in your account."
            )
            saved = DEFAULTS.get("models", {})
            models["default"] = st.text_input(
                "Main model · planning, screening, evidence",
                value=saved.get("default", os.getenv("RESEARCH_MODEL", "")),
            )
            a, b = st.columns(2)
            models["review_a"] = a.text_input(
                "Reviewer A · contribution",
                value=saved.get("review_a", os.getenv("RESEARCH_REVIEWER_A_MODEL", "")),
                placeholder="Empty = main model",
            )
            models["review_b"] = b.text_input(
                "Reviewer B · critic",
                value=saved.get("review_b", os.getenv("RESEARCH_REVIEWER_B_MODEL", "")),
                placeholder="Empty = main model",
            )
            models["adjudicate"] = st.text_input(
                "Adjudicator · resolves disagreements",
                value=saved.get("adjudicate", os.getenv("RESEARCH_ADJUDICATOR_MODEL", "")),
                placeholder="Empty = main model",
            )
            st.caption(
                "The reviewers do not see each other's answers. Different models can reduce correlated errors."
            )
            a, b = st.columns(2)
            credentials["ANTHROPIC_API_KEY"] = a.text_input(
                "Anthropic API key",
                type="password",
                key="credential_anthropic",
                placeholder="From environment" if os.getenv("ANTHROPIC_API_KEY") else "Enter the key",
            )
            credentials["OPENAI_API_KEY"] = b.text_input(
                "OpenAI API key",
                type="password",
                key="credential_openai",
                placeholder="From environment" if os.getenv("OPENAI_API_KEY") else "Enter the key",
            )
            st.caption(
                "Empty field = the key from the local environment / .env. Keys entered here are not saved to disk. The topic and abstracts are sent to the selected providers."
            )
        save = st.checkbox("Keep these settings for the next research", value=True)
        submitted = st.form_submit_button("Start research →", type="primary", use_container_width=True)
    if submitted:
        errors = []
        if len(topic.strip()) < 3:
            errors.append("Enter a topic of at least 3 characters.")
        if live:
            if not models["default"].strip():
                errors.append("Fill in the main model.")
            for value in [models["default"], *[v for k, v in models.items() if k != "default" and v.strip()]]:
                provider, separator, model = value.strip().partition(":")
                if not separator or not model or provider not in ("openai", "anthropic"):
                    errors.append("This interface accepts openai:ID and anthropic:ID models.")
                key = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(provider)
                if key and not (credentials.get(key) or os.getenv(key)):
                    errors.append(f"The key for {provider} is missing.")
        if errors:
            for error in dict.fromkeys(errors):
                st.error(error)
            return
        if save:
            atomic_json(
                ROOT / "ui-settings.json",
                {
                    "topic": topic.strip(),
                    "max_papers": maximum,
                    "models": models or DEFAULTS.get("models", {}),
                },
            )
        pauses = {
            "After search": "discover",
            "After evidence extraction": "extract",
            "After adjudication": "adjudicate",
        }
        path = new_directory(ROOT)
        try:
            launch(
                path,
                Contract(topic=topic.strip(), max_papers=maximum, mode="live" if live else "demo"),
                models=models,
                credentials=credentials,
                stop_after=pauses.get(pause),
            )
        except (ValueError, OSError) as exc:
            st.error(f"The research could not start ({type(exc).__name__}).")
            return
        st.session_state.active_run = str(path)
        st.session_state.clear_credentials = True
        st.rerun()


def review_panel(review):
    st.caption(
        f"Verdict: {review['verdict']} · relevance {review['relevance']}/4 · methods {review['methods']}/4 · support {review['support']}/4"
    )
    st.write(review["assessment"])
    st.markdown("**Strengths**")
    for item in review["strengths"]:
        st.write("• " + item)
    st.markdown("**Limitations / objections**")
    for item in review["weaknesses"]:
        st.write("• " + item)


def results(path, report):
    state = report["state"]
    papers = {p["id"]: p for p in state["papers"]}
    ranking = state["ranking"]
    counts = st.columns(4)
    for col, label, value in zip(
        counts,
        ["Records found", "Candidates reviewed", "In the ranking", "Adjudications"],
        [
            len(state["discovered"]),
            len(state["evidence"]),
            len(ranking),
            sum(d["adjudicated"] for d in state["decisions"].values()),
        ],
    ):
        col.metric(label, value)
    overview, detail, audit = st.tabs(["Ranking", "Evidence and reviewers", "Search and export"])
    with overview:
        st.subheader("Selected papers")
        st.caption(
            "Preliminary score from abstracts: relevance 40% · methodological detail 30% · support for claims 30%."
        )
        if not ranking:
            st.info(
                "No paper received the final include verdict. The candidates and reasons are in the Evidence and reviewers tab."
            )
        else:
            threshold = st.slider("Minimum score shown", 0, 100, 0, key=f"threshold-{path.name}")
            rows = [
                {
                    "Rank": i,
                    "Paper": papers[r["paper_id"]]["title"],
                    "Score": r["score"],
                    "Year": papers[r["paper_id"]]["year"],
                    "Adjudicate": "Yes" if r["decision"]["adjudicated"] else "No",
                }
                for i, r in enumerate(ranking, 1)
                if r["score"] >= threshold
            ]
            if rows:
                st.dataframe(
                    rows,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Score": st.column_config.ProgressColumn(
                            "Score / 100", min_value=0, max_value=100, format="%.1f"
                        )
                    },
                )
                for row in ranking:
                    if row["score"] < threshold:
                        continue
                    p = papers[row["paper_id"]]
                    with st.expander(f"{p['title']}  ·  {row['score']:.1f}/100"):
                        r = row["decision"]["review"]
                        st.write(r["assessment"])
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown("**Strengths**")
                            for point in r["strengths"]:
                                st.write("• " + point)
                        with c2:
                            st.markdown("**Key takeaways**")
                            for point in r["takeaways"]:
                                st.write("• " + point)
            else:
                st.info("No paper passes the chosen filter.")
    with detail:
        if not papers:
            st.info("No papers were found in the search batch.")
        else:
            pid = st.selectbox(
                "Select a paper · including unranked ones",
                list(papers),
                format_func=lambda k: papers[k]["title"],
                key=f"paper-{path.name}",
            )
            paper = papers[pid]
            st.caption(f"{pid} · {paper['year']} · DOI: {paper['doi'] or 'unavailable'}")
            st.write(
                "**Screening:** "
                + state["screens"][pid]["decision"]
                + " — "
                + state["screens"][pid]["reason"]
            )
            with st.expander("Source abstract", expanded=True):
                st.write(paper["abstract"] or "Abstract unavailable.")
            evidence = state["evidence"].get(pid)
            if evidence:
                st.markdown("**Extracted evidence**")
                for claim in evidence["claims"]:
                    with st.container(border=True):
                        st.write(claim["statement"])
                        st.caption("Exact quote from the abstract")
                        st.write(claim["quote"])
                st.caption("Design: " + evidence["study_design"])
                for limitation in evidence["limitations"]:
                    st.write("• " + limitation)
            if pid in state["reviews_a"]:
                a, b = st.columns(2)
                with a:
                    st.subheader("Reviewer A")
                    review_panel(state["reviews_a"][pid])
                with b:
                    st.subheader("Reviewer B · critic")
                    review_panel(state["reviews_b"][pid])
                d = state["decisions"][pid]
                with st.container(border=True):
                    st.markdown(
                        "**Final decision · "
                        + ("adjudicated" if d["adjudicated"] else "reviewers agreed")
                        + "**"
                    )
                    st.write(d["reason"])
                    review_panel(d["review"])
            st.markdown("**Provenance**")
            for src in paper["provenance"]:
                if src["url"].startswith("https://europepmc.org/"):
                    st.link_button("Open source · " + src["record_id"], src["url"])
                else:
                    st.text(src["url"])
                st.caption("Search: " + src["query"] + " · Retrieved: " + src["retrieved_at"])
                with st.expander("Source fingerprint"):
                    st.code(src["raw_sha256"], language=None)
    with audit:
        st.subheader("Search strategy")
        for query in state["plan"]["queries"]:
            st.code(query, language=None)
        st.write(state["plan"]["rationale"])
        st.caption("At most one page per query. The ranking covers this batch, not the whole literature.")
        with st.expander("Configuration used"):
            st.json(report["manifest"])
        a, b = st.columns(2)
        a.download_button(
            "Download the Markdown report",
            (path / "report.md").read_bytes(),
            file_name="research-report.md",
            mime="text/markdown",
            use_container_width=True,
        )
        b.download_button(
            "Download the full JSON audit",
            (path / "report.json").read_bytes(),
            file_name="research-audit.json",
            mime="application/json",
            use_container_width=True,
        )


def research(path):
    manifest = read_json(path / "manifest.json", {})
    contract = manifest.get("contract", {})
    st.caption("RESEARCH SPACE / RESULTS AND PROGRESS")
    st.title(contract.get("topic", "Preparing the research…"))
    if contract.get("mode") == "demo":
        st.info(
            "DEMO · Synthetic papers and reviews. This result demonstrates the flow; it is not scientific evidence."
        )
    elif contract:
        st.caption("LIVE · Europe PMC · abstract-only analysis · preliminary results")
    initial = status(path)

    @st.fragment(run_every=1 if initial["status"] == "running" else None)
    def monitor():
        current = status(path)
        if not contract and (path / "manifest.json").exists():
            st.rerun()
        if current["status"] != initial["status"]:
            st.rerun()
        labels = {
            "running": "Running",
            "completed": "Research complete",
            "paused": "Paused at checkpoint",
            "failed": "Research stopped with an error",
            "interrupted": "Process interrupted · can be resumed",
        }
        st.subheader(labels[current["status"]])
        stages = current.get("stages", {})
        if current["status"] == "completed":
            stages = dict.fromkeys(STAGES, "completed")
        completed = sum(v == "completed" for v in stages.values())
        st.progress(
            completed / len(STAGES),
            text=f"{completed} of {len(STAGES)} stages finished · progress by stage, not a time estimate",
        )
        symbols = {"completed": "✅", "running": "⏳", "failed": "⚠️"}
        cols = st.columns(3)
        for index, (name, label) in enumerate(STAGES.items()):
            cols[index % 3].write(symbols.get(stages.get(name), "○") + " " + label)
        if current["status"] in ("failed", "interrupted", "paused"):
            if current.get("message"):
                st.error(current["message"])
            if current.get("error_type"):
                st.caption("Error type: " + current["error_type"])
            st.caption("Resuming uses the saved configuration and existing checkpoints.")
            resume_keys = {}
            if contract.get("mode") == "live":
                with st.expander("Access for resuming · API keys"):
                    st.caption(
                        "If you entered the keys only in the interface, enter them again. Keys from .env are reused automatically."
                    )
                    resume_keys["ANTHROPIC_API_KEY"] = st.text_input(
                        "Anthropic", type="password", key="credential_anthropic"
                    )
                    resume_keys["OPENAI_API_KEY"] = st.text_input(
                        "OpenAI", type="password", key="credential_openai"
                    )
            if (path / "manifest.json").exists() and st.button("Resume research →", type="primary"):
                try:
                    launch(path, resume=True, credentials=resume_keys)
                except (ValueError, OSError):
                    st.error("Cannot resume now; check whether the research is already running.")
                else:
                    st.session_state.clear_credentials = True
                    st.rerun()
            elif not (path / "manifest.json").exists():
                st.info("The setup was not saved. Open New research to try again.")
        if current["status"] == "running":
            st.caption(
                "You can browse the library or close the page. The local process keeps running while the computer stays on."
            )

    monitor()
    report = read_json(path / "report.json")
    if report:
        st.divider()
        results(path, report)


if st.session_state.active_run:
    research(Path(st.session_state.active_run))
else:
    configuration()
