"""Evidence, relative ranking, and failure safety for topic discovery."""
import json
from pathlib import Path

import pytest

from video2yt import topic

NOW = 2_000_000_000


def candidate(bvid="BV1", streamer="A", plays=100, age=1):
    return topic.VideoCandidate(bvid, "戒指龙 36.2", "实战", 600, plays,
                                NOW - int(age * 3600), streamer)


def summary(c, **kwargs):
    return topic.VideoSummary(c, "戒指龙流", kwargs.pop("core_card", "戒指龙"),
                              "滚雪球", "新打法", **kwargs)


def output_row(**kwargs):
    return {"bvid": "BV1", "strategy": "戒指龙流", "core_card": "戒指龙",
            "summary": "滚雪球", "highlights": "新打法", "confidence": "high",
            "evidence": [{"source": "title", "quote": "戒指龙 36.2"}],
            "patch_version": "36.2", **kwargs}


def mock_codex(monkeypatch, raw):
    def run(cmd, **kwargs):
        work = Path(cmd[cmd.index("--cd") + 1])
        (work / "output.json").write_text(json.dumps(raw))
    monkeypatch.setattr(topic.subprocess, "run", run)


def run_topic(tmp_path, **kwargs):
    return topic.run_topic(streamers=[topic.Streamer("A", 1), topic.Streamer("B", 2)],
                           days=7, output_root=tmp_path / "output", done_topics_file=None,
                           report_path=tmp_path / "topics.md", now_ts=NOW, **kwargs)


def test_relative_traction_uses_age_and_streamer_baseline():
    cs = [candidate("a", "A", 1000, 10), candidate("b", "A", 2000, 10),
          candidate("c", "A", 1000, 1), candidate("d", "B", 10000, 10),
          candidate("e", "B", 20000, 10), candidate("f", "B", 10000, 1)]
    topic.normalize_traction(cs, now_ts=NOW)
    assert cs[2].relative_traction == pytest.approx(5)
    assert cs[5].relative_traction == pytest.approx(cs[2].relative_traction)
    assert cs[2].relative_traction > cs[1].relative_traction
    assert cs[0].age_hours == 10
    assert cs[0].baseline_sample_size == 3
    assert cs[0].streamer_baseline_views_per_hour == 200


def test_single_sample_and_zero_baseline_are_explicitly_unavailable():
    cs = [candidate("a", "A", 0, 0), candidate("b", "B", 0), candidate("c", "B", 0)]
    topic.normalize_traction(cs, now_ts=NOW)
    assert all(c.relative_traction is None for c in cs)
    assert cs[0].views_per_hour == 0
    assert cs[0].age_hours == 0


def test_pair_selection_uses_relative_traction_and_keeps_distinct_streamers():
    cs = [candidate("a", "A", 100000, 100), candidate("b", "A", 2000, 1),
          candidate("c", "B", 1000), candidate("d", "B", 100)]
    topic.normalize_traction(cs, now_ts=NOW)
    pairs = topic.group_pairs([summary(c) for c in cs])
    assert {s.candidate.bvid for s in pairs[0].summaries} == {"b", "c"}
    assert topic.group_pairs([summary(cs[0]), summary(cs[1])]) == []


def test_archive_corpus_survives_missing_output(tmp_path):
    archive = tmp_path / "assets/publications/yt-id"
    archive.mkdir(parents=True)
    (archive / "intro_script.txt").write_text("戒指龙以前做过")
    corpus = topic.scan_done_corpus_from_output(tmp_path / "output")
    assert corpus["assets/publications/yt-id"].endswith("戒指龙以前做过")


@pytest.mark.parametrize("raw, message", [
    ([None], "object"), ([{"strategy": "x"}], "bvid"),
    ([output_row(bvid="other")], "unknown bvid"),
    ([output_row(), output_row()], "duplicate bvid"), ([], "missing"),
    ([output_row(confidence=0.9)], "confidence"),
    ([output_row(evidence=[{"source": "title", "quote": "invented"}])], "evidence"),
    ([output_row(patch_version="99.99")], "patch_version"),
])
def test_summary_rejects_malformed_or_invented_evidence(monkeypatch, raw, message):
    mock_codex(monkeypatch, raw)
    with pytest.raises(RuntimeError, match=message):
        topic.summarize_with_codex([candidate()], {})


def test_summary_preserves_evidence_and_cannot_approve_itself(monkeypatch):
    mock_codex(monkeypatch, [output_row(verification_status="verified")])
    s = topic.summarize_with_codex([candidate()], {})[0]
    assert s.confidence == "high"
    assert s.patch_version == "36.2"
    assert s.evidence == [{"source": "title", "quote": "戒指龙 36.2"}]
    assert s.verification_status == "pending_verification"
    md = topic.render_markdown([topic.TopicPair("戒指龙", [s, s], False, None)], 7, "today")
    assert "待人工核验" in md and "36.2" in md and "title" in md and "high" in md


def test_legacy_missing_confidence_is_unavailable_and_unknown_core_abstains(monkeypatch):
    row = output_row(core_card="unknown")
    for name in ("confidence", "evidence", "patch_version"):
        row.pop(name)
    mock_codex(monkeypatch, [row])
    s = topic.summarize_with_codex([candidate()], {})[0]
    assert s.confidence is None and s.patch_version == ""
    assert s.core_card == ""
    assert topic.group_pairs([s, summary(candidate("BV2", "B"), core_card="unknown")]) == []


def test_all_fetch_failures_preserve_report_and_audit(tmp_path, monkeypatch):
    for name in ("topics.md", "topics.json"):
        (tmp_path / name).write_text("previous")
    def fail(*args, **kwargs):
        raise RuntimeError("offline")
    monkeypatch.setattr(topic, "fetch_recent_videos", fail)
    with pytest.raises(RuntimeError, match="all streamer"):
        run_topic(tmp_path)
    assert (tmp_path / "topics.md").read_text() == "previous"
    assert (tmp_path / "topics.json").read_text() == "previous"


def test_partial_fetch_failure_and_all_candidate_evidence_are_audited(tmp_path, monkeypatch):
    def fetch(s, **kwargs):
        if s.name == "B":
            raise RuntimeError("offline")
        return [candidate()]
    monkeypatch.setattr(topic, "fetch_recent_videos", fetch)
    monkeypatch.setattr(topic, "fetch_danmaku_sample", lambda *a, **kw: ["戒指龙"])
    monkeypatch.setattr(topic, "summarize_with_codex", lambda cs, dm, **kw: [summary(cs[0])])
    report = run_topic(tmp_path)
    data = json.loads(report.with_suffix(".json").read_text())
    assert data["candidates"][0]["bvid"] == "BV1"
    assert data["summaries"][0]["verification_status"] == "pending_verification"
    assert data["danmaku_by_bvid"]["BV1"] == ["戒指龙"]
    assert data["source_fetches"][1]["status"] == "failed"
    assert "B" in report.read_text() and "offline" in report.read_text()
    assert candidate().url in report.read_text()  # unpaired evidence remains reviewable


def test_successful_empty_fetch_writes_empty_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(topic, "fetch_recent_videos", lambda *a, **kw: [])
    report = run_topic(tmp_path)
    data = json.loads(report.with_suffix(".json").read_text())
    assert data["candidates"] == []
    assert all(s["status"] == "ok" for s in data["source_fetches"])


def test_normalization_default_time_and_pair_scores_are_relative(monkeypatch):
    monkeypatch.setattr(topic.time, "time", lambda: NOW)
    cs = [candidate("a", "A", 1000), candidate("b", "A", 100),
          candidate("c", "B", 100000), candidate("d", "B", 10000)]
    topic.normalize_traction(cs)
    stronger = topic.TopicPair("x", [summary(cs[0]), summary(cs[2])], False, None)
    weaker = topic.TopicPair("x", [summary(cs[1]), summary(cs[3])], False, None)
    assert topic.score_pair(stronger) > topic.score_pair(weaker)
    assert cs[0].age_hours == 1


def test_cli_exposes_fixed_scan_time():
    from video2yt import topic_cli
    assert topic_cli.parse_args(["--now-ts", str(NOW)]).now_ts == NOW


def test_danmaku_failure_is_not_disguised_as_successful_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(topic, "fetch_recent_videos", lambda s, **kw: [candidate(str(s.uid), s.name)])
    def fail(*a, **kw):
        raise RuntimeError("danmaku unavailable")
    monkeypatch.setattr(topic, "fetch_danmaku_sample", fail)
    monkeypatch.setattr(topic, "summarize_with_codex", lambda cs, dm, **kw: [summary(c) for c in cs])
    path = run_topic(tmp_path)
    data = json.loads(path.with_suffix(".json").read_text())
    assert data["danmaku_fetches"]["1"]["status"] == "failed"
    assert "danmaku unavailable" in path.read_text()


def test_invalid_summary_preserves_previous_report(tmp_path, monkeypatch):
    (tmp_path / "topics.md").write_text("previous")
    monkeypatch.setattr(topic, "fetch_recent_videos", lambda s, **kw: [candidate(str(s.uid), s.name)])
    monkeypatch.setattr(topic, "fetch_danmaku_sample", lambda *a, **kw: [])
    mock_codex(monkeypatch, [])
    with pytest.raises(RuntimeError, match="missing"):
        run_topic(tmp_path)
    assert (tmp_path / "topics.md").read_text() == "previous"
