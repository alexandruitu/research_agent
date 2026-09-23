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
    st.caption("De la întrebare la dovezi verificabile")
    if st.button("＋ Cercetare nouă", type="primary", use_container_width=True):
        st.session_state.active_run = None
        st.rerun()
    st.divider()
    st.markdown("**Biblioteca de cercetări**")
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
            "Cercetări salvate", list(labels), format_func=lambda p: labels[p], label_visibility="collapsed"
        )
        if st.button("Deschide cercetarea", use_container_width=True):
            st.session_state.active_run = choice
            st.rerun()
    else:
        st.caption("Cercetările noi vor apărea aici.")
    st.divider()
    st.caption("V1 · Analiză la nivel de abstract")
    st.caption("Europe PMC în modul live. Demo-ul folosește date sintetice.")
    st.caption("Stocare locală · SQLite · checkpoint-uri")


def configuration():
    st.caption("SPAȚIU DE CERCETARE / CONFIGURARE")
    st.title("Ce vrei să descoperi?")
    st.write(
        "Definește subiectul și evaluatorii. Urmărește cum se transformă lucrările găsite într-un clasament argumentat."
    )
    mode_label = st.radio(
        "Mod de lucru", ["Demo · fără chei API", "Live · surse și modele reale"], horizontal=True
    )
    live = mode_label.startswith("Live")
    if not live:
        st.info(
            "Demo-ul testează întregul flux cu lucrări și evaluări sintetice. Nu produce concluzii științifice."
        )
    with st.form("configuration"):
        topic = st.text_area(
            "Subiectul cercetării",
            value=DEFAULTS.get("topic", "retrieval augmented generation clinical question answering"),
            max_chars=500,
            height=90,
        )
        left, right = st.columns(2)
        maximum = left.slider("Candidați de evaluat", 1, 30, int(DEFAULTS.get("max_papers", 12)))
        pause = right.selectbox(
            "Punct de oprire", ["Fără pauză", "După căutare", "După extragerea dovezilor", "După adjudecare"]
        )
        st.caption(
            "Maximum 10 rezultate în clasament. Un lot mai mare înseamnă mai multe apeluri și un cost mai mare în modul live."
        )
        models, credentials = {}, {}
        if live:
            st.subheader("Modele și acces")
            st.caption(
                "Format model: furnizor:nume-model. De exemplu, anthropic:ID sau openai:ID. Introdu un model disponibil în contul tău."
            )
            saved = DEFAULTS.get("models", {})
            models["default"] = st.text_input(
                "Model principal · planificare, screening, dovezi",
                value=saved.get("default", os.getenv("RESEARCH_MODEL", "")),
            )
            a, b = st.columns(2)
            models["review_a"] = a.text_input(
                "Evaluator A · contribuție",
                value=saved.get("review_a", os.getenv("RESEARCH_REVIEWER_A_MODEL", "")),
                placeholder="Gol = modelul principal",
            )
            models["review_b"] = b.text_input(
                "Evaluator B · critic",
                value=saved.get("review_b", os.getenv("RESEARCH_REVIEWER_B_MODEL", "")),
                placeholder="Gol = modelul principal",
            )
            models["adjudicate"] = st.text_input(
                "Arbitru · rezolvarea dezacordurilor",
                value=saved.get("adjudicate", os.getenv("RESEARCH_ADJUDICATOR_MODEL", "")),
                placeholder="Gol = modelul principal",
            )
            st.caption(
                "Evaluatorii nu văd răspunsul celuilalt. Modelele diferite pot reduce erorile corelate."
            )
            a, b = st.columns(2)
            credentials["ANTHROPIC_API_KEY"] = a.text_input(
                "Cheie API Anthropic",
                type="password",
                key="credential_anthropic",
                placeholder="Din mediu" if os.getenv("ANTHROPIC_API_KEY") else "Introdu cheia",
            )
            credentials["OPENAI_API_KEY"] = b.text_input(
                "Cheie API OpenAI",
                type="password",
                key="credential_openai",
                placeholder="Din mediu" if os.getenv("OPENAI_API_KEY") else "Introdu cheia",
            )
            st.caption(
                "Câmp gol = cheia din mediul local / .env. Cheile introduse aici nu se salvează pe disc. Topic-ul și abstractele sunt trimise furnizorilor selectați."
            )
        save = st.checkbox("Păstrează setările pentru următoarea cercetare", value=True)
        submitted = st.form_submit_button("Pornește cercetarea →", type="primary", use_container_width=True)
    if submitted:
        errors = []
        if len(topic.strip()) < 3:
            errors.append("Introdu un subiect de cel puțin 3 caractere.")
        if live:
            if not models["default"].strip():
                errors.append("Completează modelul principal.")
            for value in [models["default"], *[v for k, v in models.items() if k != "default" and v.strip()]]:
                provider, separator, model = value.strip().partition(":")
                if not separator or not model or provider not in ("openai", "anthropic"):
                    errors.append("Interfața V1 acceptă modelele openai:ID și anthropic:ID.")
                key = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(provider)
                if key and not (credentials.get(key) or os.getenv(key)):
                    errors.append(f"Lipsește cheia pentru {provider}.")
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
            "După căutare": "discover",
            "După extragerea dovezilor": "extract",
            "După adjudecare": "adjudicate",
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
            st.error(f"Cercetarea nu a putut porni ({type(exc).__name__}).")
            return
        st.session_state.active_run = str(path)
        st.session_state.clear_credentials = True
        st.rerun()


def review_panel(review):
    st.caption(
        f"Verdict: {review['verdict']} · relevanță {review['relevance']}/4 · metodă {review['methods']}/4 · suport {review['support']}/4"
    )
    st.write(review["assessment"])
    st.markdown("**Puncte forte**")
    for item in review["strengths"]:
        st.write("• " + item)
    st.markdown("**Limite / obiecții**")
    for item in review["weaknesses"]:
        st.write("• " + item)


def results(path, report):
    state = report["state"]
    papers = {p["id"]: p for p in state["papers"]}
    ranking = state["ranking"]
    counts = st.columns(4)
    for col, label, value in zip(
        counts,
        ["Înregistrări găsite", "Candidați evaluați", "În clasament", "Adjudecări"],
        [
            len(state["discovered"]),
            len(state["evidence"]),
            len(ranking),
            sum(d["adjudicated"] for d in state["decisions"].values()),
        ],
    ):
        col.metric(label, value)
    overview, detail, audit = st.tabs(["Clasament", "Dovezi și evaluatori", "Căutare și export"])
    with overview:
        st.subheader("Lucrările selectate")
        st.caption(
            "Scor preliminar din abstracte: relevanță 40% · detalii metodologice 30% · suportul afirmațiilor 30%."
        )
        if not ranking:
            st.info(
                "Nicio lucrare nu a primit verdictul final include. Candidații și motivele sunt disponibili în fila Dovezi și evaluatori."
            )
        else:
            threshold = st.slider("Scor minim afișat", 0, 100, 0, key=f"threshold-{path.name}")
            rows = [
                {
                    "Loc": i,
                    "Lucrare": papers[r["paper_id"]]["title"],
                    "Scor": r["score"],
                    "An": papers[r["paper_id"]]["year"],
                    "Adjudecare": "Da" if r["decision"]["adjudicated"] else "Nu",
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
                        "Scor": st.column_config.ProgressColumn(
                            "Scor / 100", min_value=0, max_value=100, format="%.1f"
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
                            st.markdown("**Puncte forte**")
                            for point in r["strengths"]:
                                st.write("• " + point)
                        with c2:
                            st.markdown("**Idei principale**")
                            for point in r["takeaways"]:
                                st.write("• " + point)
            else:
                st.info("Nicio lucrare nu trece filtrul ales.")
    with detail:
        if not papers:
            st.info("Nu au fost găsite lucrări în lotul de căutare.")
        else:
            pid = st.selectbox(
                "Selectează o lucrare · inclusiv cele neclasate",
                list(papers),
                format_func=lambda k: papers[k]["title"],
                key=f"paper-{path.name}",
            )
            paper = papers[pid]
            st.caption(f"{pid} · {paper['year']} · DOI: {paper['doi'] or 'indisponibil'}")
            st.write(
                "**Screening:** "
                + state["screens"][pid]["decision"]
                + " — "
                + state["screens"][pid]["reason"]
            )
            with st.expander("Abstractul sursă", expanded=True):
                st.write(paper["abstract"] or "Abstract indisponibil.")
            evidence = state["evidence"].get(pid)
            if evidence:
                st.markdown("**Dovezi extrase**")
                for claim in evidence["claims"]:
                    with st.container(border=True):
                        st.write(claim["statement"])
                        st.caption("Citat exact din abstract")
                        st.write(claim["quote"])
                st.caption("Design: " + evidence["study_design"])
                for limitation in evidence["limitations"]:
                    st.write("• " + limitation)
            if pid in state["reviews_a"]:
                a, b = st.columns(2)
                with a:
                    st.subheader("Evaluator A")
                    review_panel(state["reviews_a"][pid])
                with b:
                    st.subheader("Evaluator B · critic")
                    review_panel(state["reviews_b"][pid])
                d = state["decisions"][pid]
                with st.container(border=True):
                    st.markdown(
                        "**Decizia finală · "
                        + ("cu adjudecare" if d["adjudicated"] else "acord între evaluatori")
                        + "**"
                    )
                    st.write(d["reason"])
                    review_panel(d["review"])
            st.markdown("**Proveniență**")
            for src in paper["provenance"]:
                if src["url"].startswith("https://europepmc.org/"):
                    st.link_button("Deschide sursa · " + src["record_id"], src["url"])
                else:
                    st.text(src["url"])
                st.caption("Căutare: " + src["query"] + " · Recuperat: " + src["retrieved_at"])
                with st.expander("Amprenta sursei"):
                    st.code(src["raw_sha256"], language=None)
    with audit:
        st.subheader("Strategia de căutare")
        for query in state["plan"]["queries"]:
            st.code(query, language=None)
        st.write(state["plan"]["rationale"])
        st.caption("Maximum o pagină per query. Clasamentul privește acest lot, nu întreaga literatură.")
        with st.expander("Configurația folosită"):
            st.json(report["manifest"])
        a, b = st.columns(2)
        a.download_button(
            "Descarcă raportul Markdown",
            (path / "report.md").read_bytes(),
            file_name="research-report.md",
            mime="text/markdown",
            use_container_width=True,
        )
        b.download_button(
            "Descarcă auditul complet JSON",
            (path / "report.json").read_bytes(),
            file_name="research-audit.json",
            mime="application/json",
            use_container_width=True,
        )


def research(path):
    manifest = read_json(path / "manifest.json", {})
    contract = manifest.get("contract", {})
    st.caption("SPAȚIU DE CERCETARE / REZULTATE ȘI PROGRES")
    st.title(contract.get("topic", "Pregătim cercetarea…"))
    if contract.get("mode") == "demo":
        st.info(
            "DEMO · Lucrări și evaluări sintetice. Acest rezultat demonstrează fluxul, nu reprezintă dovezi științifice."
        )
    elif contract:
        st.caption("LIVE · Europe PMC · analiză doar pe abstracte · rezultate preliminare")
    initial = status(path)

    @st.fragment(run_every=1 if initial["status"] == "running" else None)
    def monitor():
        current = status(path)
        if not contract and (path / "manifest.json").exists():
            st.rerun()
        if current["status"] != initial["status"]:
            st.rerun()
        labels = {
            "running": "În desfășurare",
            "completed": "Cercetare finalizată",
            "paused": "Pauză la checkpoint",
            "failed": "Cercetare oprită cu eroare",
            "interrupted": "Proces întrerupt · poate fi reluat",
        }
        st.subheader(labels[current["status"]])
        stages = current.get("stages", {})
        if current["status"] == "completed":
            stages = dict.fromkeys(STAGES, "completed")
        completed = sum(v == "completed" for v in stages.values())
        st.progress(
            completed / len(STAGES),
            text=f"{completed} din {len(STAGES)} etape încheiate · progres pe etape, nu estimare de timp",
        )
        symbols = {"completed": "✅", "running": "⏳", "failed": "⚠️"}
        cols = st.columns(3)
        for index, (name, label) in enumerate(STAGES.items()):
            cols[index % 3].write(symbols.get(stages.get(name), "○") + " " + label)
        if current["status"] in ("failed", "interrupted", "paused"):
            if current.get("message"):
                st.error(current["message"])
            if current.get("error_type"):
                st.caption("Tip eroare: " + current["error_type"])
            st.caption("Reluarea folosește configurația salvată și checkpoint-urile existente.")
            resume_keys = {}
            if contract.get("mode") == "live":
                with st.expander("Acces pentru reluare · chei API"):
                    st.caption(
                        "Dacă ai introdus cheile numai în interfață, introdu-le din nou. Cheile din .env sunt reutilizate automat."
                    )
                    resume_keys["ANTHROPIC_API_KEY"] = st.text_input(
                        "Anthropic", type="password", key="credential_anthropic"
                    )
                    resume_keys["OPENAI_API_KEY"] = st.text_input(
                        "OpenAI", type="password", key="credential_openai"
                    )
            if (path / "manifest.json").exists() and st.button("Reia cercetarea →", type="primary"):
                try:
                    launch(path, resume=True, credentials=resume_keys)
                except (ValueError, OSError):
                    st.error("Nu se poate relua acum; verifică dacă cercetarea rulează deja.")
                else:
                    st.session_state.clear_credentials = True
                    st.rerun()
            elif not (path / "manifest.json").exists():
                st.info("Configurarea nu a fost salvată. Deschide Cercetare nouă pentru a încerca din nou.")
        if current["status"] == "running":
            st.caption(
                "Poți naviga în bibliotecă sau închide pagina. Procesul local continuă cât timp calculatorul rămâne pornit."
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
