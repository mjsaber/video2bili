"""``video2yt-cleanup`` — reclaim disk after a video ships.

Run this as the LAST workflow step (after upload + subscribe comment). It:

- deletes the CURRENT project's ``temp/<source>/`` cache dirs (regenerable),
- deletes the PREVIOUS shipped project's whole ``output/<project>/`` folder.

Dry-run is the DEFAULT — it prints exactly what it would delete and how much it
would reclaim. Pass ``--yes`` to actually delete. Every target is guarded to
live strictly inside ``./temp`` or ``./output``.

Examples::

    video2yt-cleanup                       # plan for the newest shipped project
    video2yt-cleanup --project futurefish   # plan for a specific project
    video2yt-cleanup --project futurefish --yes          # do it
    video2yt-cleanup --all-previous --yes                # also sweep older projects
    video2yt-cleanup --no-prev --yes        # only purge current temp, keep all output
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from video2yt import cleanup


def _log(msg: str) -> None:
    print(f"[video2yt-cleanup] {msg}", file=sys.stderr)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-cleanup",
        description=(
            "Reclaim disk after a video ships: delete the current project's "
            "temp/ caches and the previous shipped project's output/ folder. "
            "Dry-run by default; pass --yes to delete."
        ),
    )
    parser.add_argument(
        "--project", default=None,
        help=(
            "Current (just-shipped) project: a bare name resolved under "
            "--output-dir, or omit to use the newest folder with "
            "youtube_metadata.json. Must be a SHIPPED project (carry "
            "youtube_metadata.json) and live inside --output-dir."
        ),
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("output"),
        help="Root holding project folders (default: ./output).",
    )
    parser.add_argument(
        "--temp-dir", type=Path, default=Path("temp"),
        help="Root holding per-source caches (default: ./temp).",
    )
    parser.add_argument(
        "--no-temp", dest="do_temp", action="store_false",
        help="Do NOT purge the current project's temp caches.",
    )
    parser.add_argument(
        "--no-prev", dest="do_prev", action="store_false",
        help="Do NOT delete any previous output folder (only purge temp).",
    )
    parser.add_argument(
        "--all-previous", action="store_true",
        help="Delete EVERY older shipped project's output, not just the latest one.",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Actually delete. Without this, only the dry-run plan is printed.",
    )
    parser.set_defaults(do_temp=True, do_prev=True)
    return parser.parse_args(argv)


def _print_plan(plan: cleanup.Plan, output_dir: Path) -> None:
    _log(f"current project (kept): {plan.current}")
    newer = cleanup.newer_shipped_than(output_dir, plan.current)
    if newer:
        _log(
            f"WARNING: {len(newer)} NEWER shipped project(s) exist and are kept "
            f"(the named --project is not the newest): "
            f"{', '.join(p.name for p in newer)}"
        )
    if plan.temp_targets:
        _log("temp caches to delete (current project):")
        for t in plan.temp_targets:
            _log(f"  - {t.path}  ({cleanup.human(t.size)})")
    else:
        _log("temp caches to delete: none found")
    if plan.prev_targets:
        _log("previous output folders to delete:")
        for t in plan.prev_targets:
            _log(f"  - {t.path}  ({cleanup.human(t.size)})")
    else:
        _log("previous output folders to delete: none")
    _log(f"total reclaimable: {cleanup.human(plan.total_bytes())}")


def run(args: argparse.Namespace) -> int:
    plan = cleanup.build_plan(
        output_dir=args.output_dir,
        temp_dir=args.temp_dir,
        project=args.project,
        do_temp=args.do_temp,
        do_prev=args.do_prev,
        all_previous=args.all_previous,
    )
    _print_plan(plan, args.output_dir)
    if not plan.all_targets():
        _log("nothing to delete.")
        return 0
    if not args.yes:
        _log("DRY-RUN — re-run with --yes to delete the above.")
        return 0
    deleted = cleanup.execute(plan, args.output_dir, args.temp_dir)
    reclaimed = sum(t.size for t in deleted)
    _log(f"deleted {len(deleted)} dir(s), reclaimed {cleanup.human(reclaimed)}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except ValueError as exc:
        _log(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
