"""Tests for cleanup.py + cleanup_cli — post-ship disk reclamation.

No real files outside the pytest tmp_path are ever touched; the safety guards
(assert_within) are exercised against synthetic temp/ + output/ trees.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from video2yt import cleanup, cleanup_cli


def _make_project(output_dir: Path, name: str, bvs: list[str], shipped: bool = True):
    proj = output_dir / name
    proj.mkdir(parents=True)
    if shipped:
        (proj / cleanup.METADATA_NAME).write_text("{}", encoding="utf-8")
    (proj / "intro.mp4").write_bytes(b"x" * 100)
    for bv in bvs:
        sub = proj / f"streamer：{name}-{bv}"
        sub.mkdir()
        (sub / f"{bv}_final.mp4").write_bytes(b"y" * 1000)
    return proj


def _make_temp_source(temp_dir: Path, dirname: str, bv: str, size: int = 5000):
    d = temp_dir / dirname
    d.mkdir(parents=True)
    (d / f"{bv}.mp4").write_bytes(b"z" * size)
    (d / bv).mkdir()
    (d / bv / "speech.wav").write_bytes(b"w" * size)
    return d


@pytest.fixture
def tree(tmp_path):
    out = tmp_path / "output"
    tmp = tmp_path / "temp"
    out.mkdir()
    tmp.mkdir()
    # infra folder that must never be cleaned (no metadata)
    (out / "topics").mkdir()
    (out / "topics" / "2026-06-16.md").write_text("x", encoding="utf-8")
    return tmp_path, out, tmp


# ---------------------------------------------------------------- safety

def test_assert_within_accepts_child(tmp_path):
    root = tmp_path / "temp"
    child = root / "sub"
    child.mkdir(parents=True)
    assert cleanup.assert_within(child, [root]) == child.resolve()


def test_assert_within_refuses_root_itself(tmp_path):
    root = tmp_path / "temp"
    root.mkdir()
    with pytest.raises(ValueError):
        cleanup.assert_within(root, [root])


def test_assert_within_refuses_outside(tmp_path):
    root = tmp_path / "temp"
    root.mkdir()
    with pytest.raises(ValueError):
        cleanup.assert_within(tmp_path / "elsewhere", [root])


def test_assert_within_refuses_dotdot_escape(tmp_path):
    root = tmp_path / "temp"
    root.mkdir()
    sneaky = root / ".." / "secret"
    with pytest.raises(ValueError):
        cleanup.assert_within(sneaky, [root])


# ---------------------------------------------------------------- discovery

def test_is_shipped_project_requires_metadata(tree):
    _root, out, _tmp = tree
    _make_project(out, "shipped", ["BV1p2Jg6nEJA"], shipped=True)
    _make_project(out, "wip", ["BV1eGEC6fEoW"], shipped=False)
    assert cleanup.is_shipped_project(out / "shipped")
    assert not cleanup.is_shipped_project(out / "wip")
    assert not cleanup.is_shipped_project(out / "topics")


def test_find_shipped_projects_newest_first(tree):
    _root, out, _tmp = tree
    a = _make_project(out, "alpha", ["BV1p2Jg6nEJA"])
    b = _make_project(out, "beta", ["BV1eGEC6fEoW"])
    import os
    os.utime(a, (1000, 1000))
    os.utime(b, (2000, 2000))
    names = [p.name for p in cleanup.find_shipped_projects(out)]
    assert names == ["beta", "alpha"]


def test_temp_dirs_found_by_subfolder_name(tree):
    _root, out, tmp = tree
    proj = _make_project(out, "futurefish", ["BV1p2Jg6nEJA"])
    sub_name = next(p for p in proj.iterdir() if p.is_dir()).name
    src = _make_temp_source(tmp, sub_name, "BV1p2Jg6nEJA")
    found = cleanup.temp_dirs_for_project(proj, tmp)
    assert src in found


def test_temp_dirs_found_by_bv_when_name_differs(tree):
    _root, out, tmp = tree
    proj = _make_project(out, "futurefish", ["BV1eGEC6fEoW"])
    # temp dir name does NOT match the output subfolder, but holds the BV mp4
    src = _make_temp_source(tmp, "totally-different-name", "BV1eGEC6fEoW")
    found = cleanup.temp_dirs_for_project(proj, tmp)
    assert src in found


def test_temp_dirs_ignores_unrelated_sources(tree):
    _root, out, tmp = tree
    proj = _make_project(out, "futurefish", ["BV1p2Jg6nEJA"])
    unrelated = _make_temp_source(tmp, "someone-else", "BV9zzzzzzzzz")
    found = cleanup.temp_dirs_for_project(proj, tmp)
    assert unrelated not in found


# ------------------------------------------------ resolve_current safety

def test_resolve_current_bare_name_under_output(tree):
    _root, out, tmp = tree
    _make_project(out, "futurefish", ["BV1p2Jg6nEJA"])
    cur = cleanup.resolve_current(out, "futurefish")
    assert cur.resolve() == (out / "futurefish").resolve()


def test_resolve_current_bare_name_ignores_cwd_collision(tree, monkeypatch):
    # a folder named like the project exists in cwd but NOT under output/ —
    # the bare name must still resolve under output/, not cwd.
    root, out, tmp = tree
    (root / "futurefish").mkdir()  # decoy in cwd
    monkeypatch.chdir(root)
    with pytest.raises(ValueError):  # output/futurefish doesn't exist -> not found
        cleanup.resolve_current(out, "futurefish")


def test_resolve_current_rejects_path_outside_output(tree):
    root, out, tmp = tree
    with pytest.raises(ValueError):
        cleanup.resolve_current(out, str(root))  # the tmp root, outside output/


def test_resolve_current_rejects_dotdot_escape(tree):
    _root, out, tmp = tree
    with pytest.raises(ValueError):
        cleanup.resolve_current(out, "../../etc")


def test_resolve_current_rejects_output_dir_itself(tree):
    _root, out, tmp = tree
    with pytest.raises(ValueError):
        cleanup.resolve_current(out, str(out))


def test_resolve_current_requires_shipped_project(tree):
    _root, out, tmp = tree
    (out / "wip").mkdir()  # a real folder under output/ but NOT shipped
    with pytest.raises(ValueError):
        cleanup.resolve_current(out, "wip")
    # the infra folder in the fixture (topics/, no metadata) is refused too
    with pytest.raises(ValueError):
        cleanup.resolve_current(out, "topics")


def test_cli_nonshipped_project_does_not_delete_shipped(tree):
    _root, out, tmp = tree
    real = _make_project(out, "futurefish", ["BV1p2Jg6nEJA"])  # real latest video
    (out / "scratch").mkdir()  # non-shipped folder the user fat-fingers
    rc = cleanup_cli.main(
        ["--project", "scratch", "--output-dir", str(out),
         "--temp-dir", str(tmp), "--yes"]
    )
    assert rc == 2
    assert real.exists()              # the real shipped project MUST survive
    assert (out / "topics").exists()  # infra untouched


def test_cli_project_outside_output_errors(tree):
    root, out, tmp = tree
    rc = cleanup_cli.main(
        ["--project", str(root), "--output-dir", str(out), "--temp-dir", str(tmp), "--yes"]
    )
    assert rc == 2


# ---------------------------------------------------------------- plan

def test_plan_keeps_current_deletes_prev_and_temp(tree):
    _root, out, tmp = tree
    import os
    cur = _make_project(out, "futurefish", ["BV1p2Jg6nEJA"])
    prev = _make_project(out, "golem_mech", ["BV1eGEC6fEoW"])
    os.utime(cur, (2000, 2000))
    os.utime(prev, (1000, 1000))
    sub_name = next(p for p in cur.iterdir() if p.is_dir()).name
    _make_temp_source(tmp, sub_name, "BV1p2Jg6nEJA")

    plan = cleanup.build_plan(out, tmp)  # current inferred = newest = futurefish
    assert plan.current.name == "futurefish"
    assert [t.path.name for t in plan.prev_targets] == ["golem_mech"]
    assert len(plan.temp_targets) == 1
    assert plan.total_bytes() > 0


def test_plan_all_previous_sweeps_all_older(tree):
    _root, out, tmp = tree
    import os
    for i, name in enumerate(["p_old", "p_mid", "p_cur"]):
        proj = _make_project(out, name, [f"BV{i}aaaaaaaaa"])
        os.utime(proj, (1000 + i, 1000 + i))
    plan = cleanup.build_plan(out, tmp, project="p_cur", all_previous=True)
    assert sorted(t.path.name for t in plan.prev_targets) == ["p_mid", "p_old"]

    plan1 = cleanup.build_plan(out, tmp, project="p_cur", all_previous=False)
    assert [t.path.name for t in plan1.prev_targets] == ["p_mid"]


def test_plan_stale_project_never_deletes_newer(tree):
    # naming an OLDER project as current must never delete a newer shipped video
    _root, out, tmp = tree
    import os
    old = _make_project(out, "old", ["BV1aaaaaaaaaa"])
    cur = _make_project(out, "cur", ["BV1bbbbbbbbbb"])
    newer = _make_project(out, "newer", ["BV1cccccccccc"])
    os.utime(old, (1000, 1000))
    os.utime(cur, (2000, 2000))
    os.utime(newer, (3000, 3000))

    plan = cleanup.build_plan(out, tmp, project="cur", all_previous=True)
    names = sorted(t.path.name for t in plan.prev_targets)
    assert names == ["old"]          # only older-than-cur
    assert "newer" not in names      # the newer video is protected

    plan1 = cleanup.build_plan(out, tmp, project="cur")  # single previous
    assert [t.path.name for t in plan1.prev_targets] == ["old"]


def test_cli_stale_project_warns_and_keeps_newer(tree, capsys):
    _root, out, tmp = tree
    import os
    cur = _make_project(out, "cur", ["BV1bbbbbbbbbb"])
    newer = _make_project(out, "newer", ["BV1cccccccccc"])
    os.utime(cur, (2000, 2000))
    os.utime(newer, (3000, 3000))
    rc = cleanup_cli.main(
        ["--project", "cur", "--output-dir", str(out), "--temp-dir", str(tmp), "--yes"]
    )
    assert rc == 0
    assert newer.exists()  # newer shipped video survives
    err = capsys.readouterr().err
    assert "WARNING" in err and "newer" in err


def test_newer_shipped_than_helper(tree):
    _root, out, tmp = tree
    import os
    a = _make_project(out, "a", ["BV1aaaaaaaaaa"])
    b = _make_project(out, "b", ["BV1bbbbbbbbbb"])
    os.utime(a, (1000, 1000))
    os.utime(b, (2000, 2000))
    assert [p.name for p in cleanup.newer_shipped_than(out, a)] == ["b"]
    assert cleanup.newer_shipped_than(out, b) == []


def test_no_prev_flag_keeps_all_output(tree):
    _root, out, tmp = tree
    _make_project(out, "futurefish", ["BV1p2Jg6nEJA"])
    _make_project(out, "golem_mech", ["BV1eGEC6fEoW"])
    plan = cleanup.build_plan(out, tmp, project="futurefish", do_prev=False)
    assert plan.prev_targets == []


# ---------------------------------------------------------------- execute

def test_execute_deletes_targets_only(tree):
    import os
    _root, out, tmp = tree
    prev = _make_project(out, "golem_mech", ["BV1eGEC6fEoW"])
    cur = _make_project(out, "futurefish", ["BV1p2Jg6nEJA"])
    os.utime(prev, (1000, 1000))  # current is the newest (just-shipped)
    os.utime(cur, (2000, 2000))
    sub_name = next(p for p in cur.iterdir() if p.is_dir()).name
    src = _make_temp_source(tmp, sub_name, "BV1p2Jg6nEJA")

    plan = cleanup.build_plan(out, tmp, project="futurefish")
    cleanup.execute(plan, out, tmp)

    assert not prev.exists()          # previous output gone
    assert not src.exists()           # current temp gone
    assert cur.exists()               # current output kept
    assert (out / "topics").exists()  # infra untouched


def test_execute_never_deletes_current(tree):
    _root, out, tmp = tree
    cur = _make_project(out, "futurefish", ["BV1p2Jg6nEJA"])
    # craft a malicious plan that lists the current project as a prev target
    plan = cleanup.Plan(
        current=cur,
        temp_targets=[],
        prev_targets=[cleanup.Target(cur, "output", 10)],
    )
    with pytest.raises(ValueError):
        cleanup.execute(plan, out, tmp)
    assert cur.exists()


# ---------------------------------------------------------------- cli

def test_cli_dry_run_does_not_delete(tree, capsys):
    import os
    _root, out, tmp = tree
    prev = _make_project(out, "golem_mech", ["BV1eGEC6fEoW"])
    cur = _make_project(out, "futurefish", ["BV1p2Jg6nEJA"])
    os.utime(prev, (1000, 1000))
    os.utime(cur, (2000, 2000))
    rc = cleanup_cli.main(
        ["--project", "futurefish", "--output-dir", str(out), "--temp-dir", str(tmp)]
    )
    assert rc == 0
    assert prev.exists()  # dry-run: nothing deleted
    assert "DRY-RUN" in capsys.readouterr().err


def test_cli_yes_deletes(tree, capsys):
    import os
    _root, out, tmp = tree
    prev = _make_project(out, "golem_mech", ["BV1eGEC6fEoW"])
    cur = _make_project(out, "futurefish", ["BV1p2Jg6nEJA"])
    os.utime(prev, (1000, 1000))
    os.utime(cur, (2000, 2000))
    sub_name = next(p for p in cur.iterdir() if p.is_dir()).name
    src = _make_temp_source(tmp, sub_name, "BV1p2Jg6nEJA")
    rc = cleanup_cli.main(
        ["--project", "futurefish", "--output-dir", str(out),
         "--temp-dir", str(tmp), "--yes"]
    )
    assert rc == 0
    assert not prev.exists()
    assert not src.exists()
    assert cur.exists()


def test_cli_missing_project_errors(tree):
    _root, out, tmp = tree
    rc = cleanup_cli.main(
        ["--project", "nope", "--output-dir", str(out), "--temp-dir", str(tmp)]
    )
    assert rc == 2
