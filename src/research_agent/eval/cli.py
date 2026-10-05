"""research-eval: build gold sets, screen them, run reviewer agreement, and report offline."""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from ..agents import Evaluator, live_models
from ..connectors import EuropePMC
from ..fulltext import FullText
from ..jev import JevScreener
from ..runner import review_models
from ..schemas import read_domain, read_review
from ..storage import Store
from .ablation import run_ablation
from .agreement import run_agreement
from .gold import load_gold, load_sr_spec, write_gold
from .human import RATINGS_FILE, compare_human, load_ratings
from .panel_eval import file_sha256, gold_source, load_panel_eval, run_panel_eval, run_source
from .panel_report import build_eval_report, render_eval_markdown
from .report import build_report, write_report
from .resolve import build_gold
from .screen import check_run_dir, read_manifest, run_screen, write_manifest


# Seams for tests: the real network clients are created only here.
def make_connector(store):
    return EuropePMC(store)


def make_jev(store):
    return JevScreener.from_env(store)


def make_evaluator(store, mode, models=None):
    return Evaluator(store, "demo") if mode == "demo" else Evaluator(store, "live", models or live_models())


def make_fulltext(store, spec, mode):
    return FullText(store, spec, mode=mode)


def is_eval_kind(run_dir):
    path = Path(run_dir) / "manifest.json"
    return path.exists() and json.loads(path.read_text()).get("kind") in ("panel", "ablation")


def cmd_build_gold(args):
    spec, out = load_sr_spec(args.spec), Path(args.out)
    store = Store(out.parent / f".{spec.name}.build")  # raw Europe PMC payloads for provenance
    gold = write_gold(build_gold(spec, make_connector(store), args.max_candidates), out)
    positives = sum(c.label == "include" for c in gold.candidates)
    print(
        f"Gold: {out} · {len(gold.candidates)} candidates, {positives} positives, "
        f"{len(gold.unresolved)} unresolved, {len(gold.ambiguous)} ambiguous"
    )
    return 0


def cmd_screen(args):
    gold = load_gold(args.gold)
    domain = read_domain(args.field).model_dump() if args.field else None
    check_run_dir(args.run_dir, gold, domain)  # before any API call
    store = Store(args.run_dir)
    evaluator, jev = make_evaluator(store, args.mode), make_jev(store)

    def progress(n):
        if n % 25 == 0:
            print(f"screened {n}", flush=True)

    result = run_screen(gold, store, evaluator, jev, progress, domain)
    write_manifest(
        args.run_dir,
        gold_path=args.gold,
        gold=gold,
        mode=args.mode,
        models=evaluator.models,
        jev_model=jev.model,
        screened=result,
        domain=domain,
    )
    print(
        f"Screened {result['screened']} candidates · Jev {result['jev_model_versions']} · run: {args.run_dir}"
    )
    return 0


def cmd_agreement(args):
    manifest = read_manifest(args.run_dir)
    gold = load_gold(args.gold)
    if gold.content_sha256 != manifest["gold_sha256"]:
        raise ValueError("gold file differs from the one this run screened")
    # Same mode and models as the screening run, so the audit and the report's same-family check agree.
    evaluator = make_evaluator(Store(args.run_dir), manifest["mode"], manifest["models"])
    print(f"Agreement: {run_agreement(gold, args.run_dir, evaluator, args.limit)}")
    return 0


def cmd_panel(args):
    spec = read_review(args.review)
    review = spec.model_dump()
    if args.gold:
        gold = load_gold(args.gold)
        topic, papers, rows = gold_source(gold)
        source = {"gold_path": str(Path(args.gold).resolve()), "gold_sha256": gold.content_sha256}
    else:
        topic, papers, rows = run_source(args.run)
        report = Path(args.run) / "report.json"
        source = {"run_dir": str(Path(args.run).resolve()), "report_sha256": file_sha256(report)}
    store = Store(args.eval_dir)
    keys = [r["key"] for r in review["panel"]]
    models = None if args.mode == "demo" else live_models(review_models(spec), panel=keys)
    evaluator = make_evaluator(store, args.mode, models)
    data = run_panel_eval(
        args.eval_dir,
        topic=topic,
        papers=papers,
        rows=rows,
        labels={r["id"]: r["label"] for r in rows},
        source=source,
        review=review,
        review_path=args.review,
        evaluator=evaluator,
        fulltext=make_fulltext(store, review["fulltext"], args.mode),
        n=args.sample,
        seed=args.seed,
        mode=args.mode,
    )
    print(f"Panel eval: {len(data['papers'])} papers · {len(keys)} reviewers · {args.eval_dir}")
    return 0


def cmd_ablation(args):
    evaluator = None
    if args.rerun_editor:
        _manifest, review, _data = load_panel_eval(args.panel_dir)
        spec = read_review(Path(args.panel_dir) / "review.json")
        keys = [r["key"] for r in review["panel"]]
        models = None if args.mode == "demo" else live_models(review_models(spec), panel=keys)
        evaluator = make_evaluator(Store(args.eval_dir), args.mode, models)
    data = run_ablation(
        args.panel_dir, args.eval_dir, rerun_editor=args.rerun_editor, evaluator=evaluator, mode=args.mode
    )
    print(f"Ablation: {len(data['subsets'])} reviewer subsets · {args.eval_dir}")
    return 0


def cmd_human(args):
    eval_dir = Path(args.eval_dir)
    _manifest, review, panel_data = load_panel_eval(eval_dir)
    source = Path(args.ratings) if args.ratings else eval_dir / RATINGS_FILE
    ratings = load_ratings(source)  # validates before the file is copied in
    target = eval_dir / RATINGS_FILE
    if source.resolve() != target.resolve():
        target.write_bytes(source.read_bytes())
    out = compare_human(review, panel_data, ratings)
    print(
        f"Human reference: {out['ratings']} ratings · {out['units']} rated items · {out['stale_or_unknown']} stale"
    )
    return 0


def cmd_report(args):
    if is_eval_kind(args.run_dir):
        report = build_eval_report(args.run_dir)
        directory = Path(args.run_dir)
        (directory / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        (directory / "metrics.md").write_text(render_eval_markdown(report))
        print(f"Report: {directory / 'metrics.md'} · {report['kind']}")
        return 0
    report = build_report(args.run_dir, args.target_recall, args.holdout, args.allow_mixed_jev_versions)
    write_report(args.run_dir, report)
    best = report["recommended"]
    print(
        f"Report: {Path(args.run_dir) / 'metrics.md'} · recommended: "
        + (f"include>={best['min_confidence']} exclude>={best['exclude_min_confidence']}" if best else "none")
    )
    return 0


def non_negative_int(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {value}")
    return value


def positive_int(text):
    value = non_negative_int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {value}")
    return value


def build_parser():
    parser = argparse.ArgumentParser(prog="research-eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build-gold", help="resolve an SR's included studies and freeze a gold set")
    p.add_argument("spec")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--max-candidates", type=int, default=200)
    p.set_defaults(func=cmd_build_gold)

    p = sub.add_parser("screen", help="run Jev and the LLM screen on every candidate")
    p.add_argument("gold")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--mode", choices=["live", "demo"], default="live")
    p.add_argument("--field", help="screen with a field's criteria (a domain.json file)")
    p.set_defaults(func=cmd_screen)

    p = sub.add_parser("agreement", help="reviewers A/B on all positives plus sampled negatives")
    p.add_argument("gold")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--limit", type=non_negative_int, default=40, help="number of negatives sampled")
    p.set_defaults(func=cmd_agreement)

    p = sub.add_parser("panel", help="full text + review panel + editor on a sample of papers (cached)")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--gold", help="a frozen gold set (SR labels: AUC is computed)")
    source.add_argument("--run", help="a finished run folder (no labels)")
    p.add_argument("--review", required=True, help="review.json with the panel to evaluate")
    p.add_argument("--eval-dir", required=True)
    p.add_argument("--sample", type=positive_int, default=20, help="number of papers")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--mode", choices=["live", "demo"], default="live")
    p.set_defaults(func=cmd_panel)

    p = sub.add_parser("ablation", help="every reviewer subset of a panel eval, offline")
    p.add_argument("panel_dir")
    p.add_argument("--eval-dir", required=True)
    p.add_argument("--rerun-editor", action="store_true", help="ask the editor per subset (costs calls)")
    p.add_argument("--mode", choices=["live", "demo"], default="live")
    p.set_defaults(func=cmd_ablation)

    p = sub.add_parser("human", help="compare a panel eval with human reference ratings")
    p.add_argument("eval_dir")
    p.add_argument("--ratings", help="human_ratings.json (copied into the eval folder)")
    p.set_defaults(func=cmd_human)

    p = sub.add_parser("report", help="offline metrics from cached calls")
    p.add_argument("run_dir")
    p.add_argument(
        "--target-recall", type=float, default=None, help="optional extra constraint: recall >= this"
    )
    p.add_argument("--holdout", help="run dir of a second, already-screened SR")
    p.add_argument("--allow-mixed-jev-versions", action="store_true")
    p.set_defaults(func=cmd_report)
    return parser


def redact(message):
    """Replace the value of every *_API_KEY environment variable (if >= 8 chars) with ***."""
    for name, value in os.environ.items():
        if name.endswith("_API_KEY") and len(value) >= 8:
            message = message.replace(value, "***")
    return message


def log_dir(args):
    if args.command == "build-gold":
        return Path(args.out).parent
    if args.command in ("panel", "ablation", "human"):
        return Path(args.eval_dir)
    return Path(args.run_dir)


def main(argv=None, dotenv=True):
    args = build_parser().parse_args(argv)
    if dotenv:  # tests pass dotenv=False so real keys from .env never leak into the test process
        load_dotenv(".env")
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 -- CLI boundary: log type + message, never keys
        directory = log_dir(args)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "errors.log").write_text(f"{type(exc).__name__}: {redact(str(exc))[:2000]}\n")
        print(
            f"research-eval stopped ({type(exc).__name__}); details in {directory / 'errors.log'}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
