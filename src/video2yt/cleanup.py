"""Project cleanup — reclaim disk after a video ships.

Policy (locked 2026-06-18, user has limited storage):

- **CURRENT project**: delete its ``temp/<source>/`` cache dirs (raw mp4 +
  stems + sidecars are all regenerable), but KEEP ``output/<project>/`` as a
  one-period buffer.
- **PREVIOUS project(s)**: delete the entire ``output/<project>/`` folder —
  the shipped video already lives on YouTube.

Safety is the whole point of this module (a prior over-broad ``rm -rf
temp/*<glob>*`` once wiped unrelated caches). Every delete is funnelled through
``assert_within`` so a target MUST resolve strictly inside ``<repo>/temp`` or
``<repo>/output``; the roots themselves and anything outside are refused. The
CLI is dry-run by default.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")
METADATA_NAME = "youtube_metadata.json"


def dir_size(path: Path) -> int:
    """Total bytes under ``path`` (symlinks counted as their own size, not
    followed)."""
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += (Path(root) / name).lstat().st_size
            except OSError:
                pass
    return total


def human(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.1f}{unit}"
        f /= 1024
    return f"{f:.1f}TB"


def assert_within(path: Path, roots: list[Path]) -> Path:
    """Resolve ``path`` and require it to live strictly *inside* one of
    ``roots``. Refuses a root itself and anything outside every root."""
    rp = path.resolve()
    for root in roots:
        rr = root.resolve()
        if rp == rr:
            raise ValueError(f"refusing to operate on a root directory itself: {rp}")
        if rr in rp.parents:
            return rp
    raise ValueError(
        f"refusing to touch {rp}: not inside any allowed root "
        f"({', '.join(str(r.resolve()) for r in roots)})"
    )


def is_shipped_project(p: Path) -> bool:
    """A folder is a shipped video project iff it carries the upload manifest.
    This is what distinguishes real projects from infra folders (topics/,
    avatar/, scratch dirs) that must never be cleaned."""
    return p.is_dir() and (p / METADATA_NAME).is_file()


def find_shipped_projects(output_dir: Path) -> list[Path]:
    """Shipped project folders under ``output_dir``, newest first (by mtime)."""
    if not output_dir.is_dir():
        return []
    projs = [d for d in output_dir.iterdir() if is_shipped_project(d)]
    return sorted(projs, key=lambda d: d.stat().st_mtime, reverse=True)


def newer_shipped_than(output_dir: Path, current: Path) -> list[Path]:
    """Shipped projects strictly NEWER than ``current`` — the ones a stale
    ``--project`` would otherwise be at risk of deleting. They are always kept;
    the CLI surfaces them so naming a stale project is obvious."""
    cur_mtime = current.stat().st_mtime
    cur_res = current.resolve()
    return [
        p for p in find_shipped_projects(output_dir)
        if p.resolve() != cur_res and p.stat().st_mtime > cur_mtime
    ]


def bvids_in_project(project_dir: Path) -> set[str]:
    """Every BV id referenced by a file name anywhere under the project."""
    bvs: set[str] = set()
    for p in project_dir.rglob("*"):
        bvs.update(BV_RE.findall(p.name))
    return bvs


def temp_dirs_for_project(project_dir: Path, temp_dir: Path) -> list[Path]:
    """Source temp dirs belonging to ``project_dir``, found by two independent
    signals so a rename of either side still leaves one working link:

    1. an output segment subfolder whose name matches a ``temp/<name>/`` dir;
    2. a ``temp/<name>/`` dir holding a ``<bv>.mp4`` for a BV referenced in the
       project.
    """
    if not temp_dir.is_dir():
        return []
    found: dict[str, Path] = {}
    # (1) subfolder-name match
    for sub in project_dir.iterdir():
        if sub.is_dir():
            cand = temp_dir / sub.name
            if cand.is_dir():
                found[cand.name] = cand
    # (2) bv match
    bvids = bvids_in_project(project_dir)
    if bvids:
        for d in temp_dir.iterdir():
            if d.is_dir() and any((d / f"{bv}.mp4").exists() for bv in bvids):
                found[d.name] = d
    return sorted(found.values(), key=lambda d: d.name)


@dataclass
class Target:
    path: Path
    kind: str  # "temp" | "output"
    size: int


@dataclass
class Plan:
    current: Path
    temp_targets: list[Target]
    prev_targets: list[Target]

    def all_targets(self) -> list[Target]:
        return self.temp_targets + self.prev_targets

    def total_bytes(self) -> int:
        return sum(t.size for t in self.all_targets())


def resolve_current(output_dir: Path, project: str | Path | None) -> Path:
    """Resolve the 'current' project folder. ``project`` may be a bare name
    (always resolved under ``output_dir`` — never cwd), a path *inside*
    ``output_dir``, or None (newest shipped). A value that resolves outside
    ``output_dir`` is refused, so a stray name/path can never make cleanup
    operate on an unrelated tree."""
    if project is None:
        shipped = find_shipped_projects(output_dir)
        if not shipped:
            raise ValueError(
                f"no shipped project (folder with {METADATA_NAME}) found under "
                f"{output_dir.resolve()}; pass --project explicitly"
            )
        return shipped[0]
    name = str(project)
    p = Path(project)
    if os.sep not in name and not p.is_absolute():
        # bare name → ALWAYS under output_dir, regardless of any cwd collision
        p = output_dir / name
    out_res = output_dir.resolve()
    if out_res not in p.resolve().parents:
        raise ValueError(
            f"--project must be a folder under {out_res}, got {p.resolve()}"
        )
    if not p.is_dir():
        raise ValueError(f"--project not found: {p}")
    if not is_shipped_project(p):
        raise ValueError(
            f"--project {p} is not a shipped project (no {METADATA_NAME}). "
            f"Refusing: cleanup is a post-ship step, and pointing it at a "
            f"non-shipped folder would treat your real latest video as the "
            f"'previous' project and delete it."
        )
    return p


def build_plan(
    output_dir: Path,
    temp_dir: Path,
    project: str | Path | None = None,
    do_temp: bool = True,
    do_prev: bool = True,
    all_previous: bool = False,
) -> Plan:
    current = resolve_current(output_dir, project)
    temp_targets: list[Target] = []
    if do_temp:
        temp_targets = [
            Target(d, "temp", dir_size(d))
            for d in temp_dirs_for_project(current, temp_dir)
        ]
    prev_targets: list[Target] = []
    if do_prev:
        # "previous" means strictly OLDER than the current project. Naming a
        # stale --project must never delete a newer shipped video — only ones
        # that predate the named current. find_shipped_projects is newest-first,
        # so after this filter others[:1] is the true immediately-previous one.
        current_mtime = current.stat().st_mtime
        others = [
            p for p in find_shipped_projects(output_dir)
            if p.resolve() != current.resolve()
            and p.stat().st_mtime < current_mtime
        ]
        if not all_previous:
            others = others[:1]
        prev_targets = [Target(p, "output", dir_size(p)) for p in others]
    return Plan(current=current, temp_targets=temp_targets, prev_targets=prev_targets)


def execute(plan: Plan, output_dir: Path, temp_dir: Path) -> list[Target]:
    """Delete every target, each re-checked against the allowed roots and never
    equal to the current project. Returns what was deleted."""
    roots = [output_dir, temp_dir]
    current_resolved = plan.current.resolve()
    deleted: list[Target] = []
    for t in plan.all_targets():
        safe = assert_within(t.path, roots)
        if safe == current_resolved:
            raise ValueError(f"refusing to delete the current project: {safe}")
        shutil.rmtree(safe)
        deleted.append(t)
    return deleted
