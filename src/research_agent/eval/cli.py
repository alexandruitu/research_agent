"""research-eval: build gold sets, screen them, run reviewer agreement, and report offline."""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from ..agents import Evaluator, live_models
from ..connectors import EuropePMC
from ..jev import JevScreener
from ..storage import Store
from .agreement import run_agreement
from .gold import load_gold, load_sr_spec, write_gold
from .report import build_report, write_report
from .resolve import build_gold
from .screen import read_manifest, run_screen, write_manifest


# Seams for tests: the real network clients are created only here.
def make_connector(store):
    return EuropePMC(store)


def make_jev(store):
    return JevScreener.from_env(store)


def make_evaluator(store, mode, models=None):
    return Evaluator(store, "demo") if mode == "demo" else Evaluator(store, "live", models or live_models())


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
    store = Store(args.run_dir)
    evaluator, jev = make_evaluator(store, args.mode), make_jev(store)

    def progress(n):
        if n % 25 == 0:
            print(f"screened {n}", flush=True)

    result = run_screen(gold, store, evaluator, jev, progress)
    write_manifest(
        args.run_dir,
        gold_path=args.gold,
        gold=gold,
        mode=args.mode,
        models=evaluator.models,
        jev_model=jev.model,
        screened=result,
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


def cmd_report(args):
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
    p.set_defaults(func=cmd_screen)

    p = sub.add_parser("agreement", help="reviewers A/B on all positives plus sampled negatives")
    p.add_argument("gold")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--limit", type=non_negative_int, default=40, help="number of negatives sampled")
    p.set_defaults(func=cmd_agreement)

    p = sub.add_parser("report", help="offline metrics from cached calls")
    p.add_argument("run_dir")
    p.add_argument("--target-recall", type=float, default=0.98)
    p.add_argument("--holdout", help="run dir of a second, already-screened SR")
    p.add_argument("--allow-mixed-jev-versions", action="store_true")
    p.set_defaults(func=cmd_report)
    return parser


def log_dir(args):
    return Path(args.out).parent if args.command == "build-gold" else Path(args.run_dir)


def main(argv=None, dotenv=True):
    args = build_parser().parse_args(argv)
    if dotenv:  # tests pass dotenv=False so real keys from .env never leak into the test process
        load_dotenv(".env")
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 -- CLI boundary: log type + message, never keys
        directory = log_dir(args)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "errors.log").write_text(f"{type(exc).__name__}: {str(exc)[:2000]}\n")
        print(
            f"research-eval stopped ({type(exc).__name__}); details in {directory / 'errors.log'}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
