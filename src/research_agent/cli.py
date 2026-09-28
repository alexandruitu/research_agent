import argparse
from pathlib import Path

from dotenv import load_dotenv

from .runner import RunLocked, run_research
from .schemas import Contract, DomainError, read_domain

EXIT_LOCKED = 75  # os.EX_TEMPFAIL: another process is running this folder; try again later


def main():
    parser = argparse.ArgumentParser(description="Abstract-level research pipeline; demo is synthetic.")
    parser.add_argument("topic", nargs="?")
    parser.add_argument("--domain", type=Path, help="field definition (domain.json) instead of a topic")
    parser.add_argument("--mode", choices=["demo", "live"], default="demo")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--max-papers", type=int, default=12)
    parser.add_argument("--jev", action="store_true", help="Jev classifier as screening tier 1 (live only)")
    parser.add_argument("--jev-min-confidence", type=float, default=None, help="auto-include threshold (0.6)")
    parser.add_argument(
        "--jev-exclude-min-confidence",
        type=float,
        default=None,
        help="auto-exclude threshold (0.9, stricter)",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after", choices=["discover", "extract", "adjudicate"])
    args = parser.parse_args()
    load_dotenv()
    if args.domain and args.topic:
        parser.error("Give either a topic or --domain, not both")
    if args.domain and args.resume:
        parser.error("--resume reads the saved run; do not pass --domain")
    if args.domain and (args.jev_min_confidence is not None or args.jev_exclude_min_confidence is not None):
        parser.error("With --domain the Jev thresholds come from domain.json")
    if not args.resume and not (args.topic or args.domain):
        parser.error("Topic or --domain is required for a new run")
    domain = None
    if args.domain:
        try:
            domain = read_domain(args.domain)
        except DomainError as exc:
            parser.error(str(exc))
    contract = (
        Contract(
            topic=domain.topic if domain else args.topic,
            domain=domain,
            mode=args.mode,
            max_papers=args.max_papers,
            jev=args.jev,
            jev_min_confidence=0.6 if args.jev_min_confidence is None else args.jev_min_confidence,
            jev_exclude_min_confidence=0.9
            if args.jev_exclude_min_confidence is None
            else args.jev_exclude_min_confidence,
        )
        if args.topic or domain
        else None
    )
    try:
        result = run_research(
            args.run_dir,
            contract=contract,
            resume=args.resume,
            stop_after=args.stop_after,
            on_event=lambda event: print("Completed:", ", ".join(event), flush=True),
            domain_file=args.domain,
        )
    except RunLocked:
        parser.exit(
            EXIT_LOCKED, "This research is already running in this folder; try again when it finishes.\n"
        )
    except Exception as exc:  # noqa: BLE001 -- CLI boundary deliberately sanitizes provider errors.
        parser.exit(
            1, f"Research stopped ({type(exc).__name__}). Check configuration and resume the saved run.\n"
        )
    print(
        f"Report: {args.run_dir / 'report.md'}" if result is not None else "Checkpoint saved. Use --resume."
    )


if __name__ == "__main__":
    main()
