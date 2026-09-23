import argparse
from pathlib import Path

from dotenv import load_dotenv

from .runner import run_research
from .schemas import Contract


def main():
    parser = argparse.ArgumentParser(description="Abstract-level research pipeline; demo is synthetic.")
    parser.add_argument("topic", nargs="?")
    parser.add_argument("--mode", choices=["demo", "live"], default="demo")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--max-papers", type=int, default=12)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after", choices=["discover", "extract", "adjudicate"])
    args = parser.parse_args()
    load_dotenv()
    if not args.resume and not args.topic:
        parser.error("Topic is required for a new run")
    contract = Contract(topic=args.topic, mode=args.mode, max_papers=args.max_papers) if args.topic else None
    try:
        result = run_research(
            args.run_dir,
            contract=contract,
            resume=args.resume,
            stop_after=args.stop_after,
            on_event=lambda event: print("Completed:", ", ".join(event), flush=True),
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
