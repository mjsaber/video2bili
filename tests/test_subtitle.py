"""Unit tests for video2yt-subtitle (Stage 3).

After T4 of the speech2srt-integration plan, the only code paths exercised
here are the subtitle_cli wrapper around the external ``speech2srt`` CLI.
The legacy ``src/video2yt/subtitle.py`` module (whisperx ASR + ffmpeg
silencedetect pause-split + codex cleanup + manual ASS splitter + danmaku
/ OCR detection helpers) was deleted in T4 — those tests are gone with it.

All subprocess boundaries are mocked.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from video2yt import subtitle_cli, validate


# ---------------------------------------------------------------------------
# argparse + preflight
# ---------------------------------------------------------------------------


def test_parse_args_defaults():
    args = subtitle_cli.parse_args(["seg.mp4"])
    assert args.segment == Path("seg.mp4")
    assert args.context_file is None
    assert args.skip_cleanup is False
    assert args.force_asr is False
    assert args.font_face == "Hiragino Sans GB"
    assert args.outline_px == 4
    assert args.shadow_px == 2
    assert args.margin_v == 80


def test_parse_args_no_longer_accepts_legacy_flags():
    """Detection flags were dropped earlier (T4 of step6-restructure); T3 of
    speech2srt-integration dropped --force-cleanup / --glossary /
    --pause-split-seconds. Any of these should error out of argparse."""
    detection_flags = [
        ("--force-add", None), ("--force-skip", None),
        ("--enable-ocr", None), ("--danmaku", "d.xml"),
        ("--ocr-interval", "5"),
    ]
    t3_removed_flags = [
        ("--force-cleanup", None),
        ("--glossary", "g.yaml"),
        ("--pause-split-seconds", "0.6"),
    ]
    for flag, value in detection_flags + t3_removed_flags:
        with pytest.raises(SystemExit):
            if value is None:
                subtitle_cli.parse_args(["seg.mp4", flag])
            else:
                subtitle_cli.parse_args(["seg.mp4", flag, value])


@patch("video2yt.subtitle_cli.shutil.which")
def test_preflight_fails_when_ffmpeg_missing(mock_which):
    mock_which.return_value = None
    with pytest.raises(RuntimeError, match="ffmpeg"):
        subtitle_cli.preflight()


def test_preflight_fails_when_speech2srt_missing(monkeypatch):
    """T3: preflight catches missing speech2srt CLI with install instructions."""
    def which(cmd):
        return "/usr/bin/found" if cmd in ("ffmpeg", "ffprobe") else None
    monkeypatch.setattr("video2yt.subtitle_cli.shutil.which", which)
    with pytest.raises(RuntimeError, match="speech2srt"):
        subtitle_cli.preflight()


# ---------------------------------------------------------------------------
# T3 CLI tests (speech2srt-integration plan): subprocess wiring + contract.
# ---------------------------------------------------------------------------


_FAKE_SRT = (
    "1\n00:00:01,000 --> 00:00:02,000\n你好\n\n"
    "2\n00:00:03,000 --> 00:00:04,000\n世界\n"
)


def _setup_subtitle_cli_fixture(tmp_path, monkeypatch):
    """Return (seg_mp4, bv_dir, speech_wav) with the inputs Stage 3 expects,
    plus a default subprocess.run mock that simulates a successful speech2srt
    run by writing _FAKE_SRT to the -o path. Tests can monkeypatch
    `video2yt.subtitle_cli.subprocess.run` again to override.
    """
    seg_mp4 = tmp_path / "x.mp4"
    seg_mp4.write_bytes(b"video-bytes")
    bv_dir = tmp_path / "x"
    bv_dir.mkdir()
    speech_wav = bv_dir / "speech.wav"
    speech_wav.write_bytes(b"PCM-speech")

    monkeypatch.setattr("video2yt.subtitle_cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.validate.probe",
        lambda path: validate.MediaInfo(
            duration=300.0, width=1920, height=1080,
            has_video=True, has_audio=True,
            vcodec="h264", acodec="aac", size_bytes=1,
        ),
    )

    def fake_speech2srt_run(argv, **kwargs):
        try:
            out_idx = argv.index("-o")
            out_path = Path(argv[out_idx + 1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(_FAKE_SRT, encoding="utf-8")
        except (ValueError, IndexError):
            pass
        return subprocess.CompletedProcess(args=argv, returncode=0,
                                           stdout="", stderr="")

    monkeypatch.setattr(
        "video2yt.subtitle_cli.subprocess.run", fake_speech2srt_run,
    )
    return seg_mp4, bv_dir, speech_wav


def test_cli_errors_when_speech_wav_missing(tmp_path, monkeypatch):
    """subtitle_cli requires <bv>/speech.wav as a sibling. No silent
    fallback — the user must run video2yt-stems first."""
    monkeypatch.setattr("video2yt.subtitle_cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.validate.probe",
        lambda path: validate.MediaInfo(
            duration=60.0, width=1920, height=1080,
            has_video=True, has_audio=True,
            vcodec="h264", acodec="aac", size_bytes=1,
        ),
    )
    seg_mp4 = tmp_path / "x.mp4"
    seg_mp4.write_bytes(b"v")

    args = subtitle_cli.parse_args([str(seg_mp4)])
    with pytest.raises(FileNotFoundError, match="required stem not found"):
        subtitle_cli.run(args)


def test_t3_cli_invokes_speech2srt_with_expected_argv(tmp_path, monkeypatch):
    """T3 #1: locked argv contract — positional wav + -o + max-line-chars +
    --force + --cleanup + --context-file (when context is set)."""
    seg_mp4, bv_dir, speech_wav = _setup_subtitle_cli_fixture(tmp_path, monkeypatch)
    captured_argv: list[list[str]] = []

    def capture(argv, **kwargs):
        captured_argv.append(list(argv))
        out_idx = argv.index("-o")
        Path(argv[out_idx + 1]).write_text(_FAKE_SRT, encoding="utf-8")
        return subprocess.CompletedProcess(args=argv, returncode=0,
                                           stdout="", stderr="")

    monkeypatch.setattr("video2yt.subtitle_cli.subprocess.run", capture)

    ctx = tmp_path / "ctx.txt"
    ctx.write_text("background", encoding="utf-8")

    args = subtitle_cli.parse_args([
        str(seg_mp4), "--context-file", str(ctx),
    ])
    subtitle_cli.run(args)

    assert len(captured_argv) == 1
    argv = captured_argv[0]
    assert argv[0] == "speech2srt"
    assert argv[1] == str(speech_wav)
    assert "-o" in argv
    o_idx = argv.index("-o")
    assert argv[o_idx + 1] == str(bv_dir / "speech.cleaned.srt")
    assert "--max-line-chars" in argv
    assert "--force" in argv
    assert "--cleanup" in argv
    assert "--context-file" in argv
    cf_idx = argv.index("--context-file")
    assert argv[cf_idx + 1] == str(ctx)
    assert "--no-cache" not in argv


def test_t3_cli_passes_max_line_chars_from_compose_helper(tmp_path, monkeypatch):
    """T3 #2: --max-line-chars matches compose._effective_chars_per_line
    output for the same font_size + video_width."""
    seg_mp4, bv_dir, speech_wav = _setup_subtitle_cli_fixture(tmp_path, monkeypatch)
    captured_argv: list[list[str]] = []

    def capture(argv, **kwargs):
        captured_argv.append(list(argv))
        out_idx = argv.index("-o")
        Path(argv[out_idx + 1]).write_text(_FAKE_SRT, encoding="utf-8")
        return subprocess.CompletedProcess(args=argv, returncode=0,
                                           stdout="", stderr="")
    monkeypatch.setattr("video2yt.subtitle_cli.subprocess.run", capture)

    from video2yt.compose import _effective_chars_per_line
    args = subtitle_cli.parse_args([str(seg_mp4), "--font-size", "60"])
    subtitle_cli.run(args)

    expected = _effective_chars_per_line(
        font_size=60, video_width=1920, margin_l=80, margin_r=80,
    )
    argv = captured_argv[0]
    mlc_idx = argv.index("--max-line-chars")
    assert int(argv[mlc_idx + 1]) == expected


def test_t3_cli_force_asr_deletes_speech2srt_sidecars_and_omits_no_cache(
    tmp_path, monkeypatch,
):
    """T3 #3: --force-asr deletes <wav>.speech2srt.json + .srt sidecars and
    runs WITHOUT --no-cache (so the fresh result repopulates the cache)."""
    seg_mp4, bv_dir, speech_wav = _setup_subtitle_cli_fixture(tmp_path, monkeypatch)
    sidecar_json = speech_wav.parent / f"{speech_wav.name}.speech2srt.json"
    sidecar_srt = speech_wav.parent / f"{speech_wav.name}.speech2srt.srt"
    sidecar_json.write_text("{}", encoding="utf-8")
    sidecar_srt.write_text("stale srt", encoding="utf-8")

    captured_argv: list[list[str]] = []
    sidecars_at_subprocess_time: list[tuple[bool, bool]] = []

    def capture(argv, **kwargs):
        captured_argv.append(list(argv))
        sidecars_at_subprocess_time.append(
            (sidecar_json.exists(), sidecar_srt.exists())
        )
        out_idx = argv.index("-o")
        Path(argv[out_idx + 1]).write_text(_FAKE_SRT, encoding="utf-8")
        return subprocess.CompletedProcess(args=argv, returncode=0,
                                           stdout="", stderr="")
    monkeypatch.setattr("video2yt.subtitle_cli.subprocess.run", capture)

    args = subtitle_cli.parse_args([str(seg_mp4), "--force-asr"])
    subtitle_cli.run(args)

    assert sidecars_at_subprocess_time == [(False, False)]
    assert "--no-cache" not in captured_argv[0]


def test_t3_cli_force_asr_tolerates_missing_sidecars(tmp_path, monkeypatch):
    """T3 #4: --force-asr on a cold run (no sidecars yet) must not raise."""
    seg_mp4, bv_dir, speech_wav = _setup_subtitle_cli_fixture(tmp_path, monkeypatch)
    args = subtitle_cli.parse_args([str(seg_mp4), "--force-asr"])
    subtitle_cli.run(args)


def test_t3_cli_skip_cleanup_omits_cleanup_and_context_file(
    tmp_path, monkeypatch,
):
    """T3 #5: --skip-cleanup omits both --cleanup and --context-file from argv."""
    seg_mp4, bv_dir, speech_wav = _setup_subtitle_cli_fixture(tmp_path, monkeypatch)
    captured: list[list[str]] = []

    def capture(argv, **kwargs):
        captured.append(list(argv))
        out_idx = argv.index("-o")
        Path(argv[out_idx + 1]).write_text(_FAKE_SRT, encoding="utf-8")
        return subprocess.CompletedProcess(args=argv, returncode=0,
                                           stdout="", stderr="")
    monkeypatch.setattr("video2yt.subtitle_cli.subprocess.run", capture)

    ctx = tmp_path / "ctx.txt"
    ctx.write_text("bg", encoding="utf-8")

    args = subtitle_cli.parse_args([
        str(seg_mp4), "--skip-cleanup", "--context-file", str(ctx),
    ])
    subtitle_cli.run(args)

    argv = captured[0]
    assert "--cleanup" not in argv
    assert "--context-file" not in argv


def test_t3_cli_reads_speech2srt_srt_output_and_writes_speech_cleaned_ass(
    tmp_path, monkeypatch,
):
    """T3 #6: speech2srt writes a known SRT → run() converts it to ASS at
    <bv>/speech.cleaned.ass containing the dialogue lines."""
    seg_mp4, bv_dir, speech_wav = _setup_subtitle_cli_fixture(tmp_path, monkeypatch)

    args = subtitle_cli.parse_args([str(seg_mp4)])
    cleaned_ass = subtitle_cli.run(args)

    assert cleaned_ass == bv_dir / "speech.cleaned.ass"
    text = cleaned_ass.read_text(encoding="utf-8")
    assert "[Script Info]" in text
    assert "PlayResX: 1920" in text
    assert "PlayResY: 1080" in text
    assert "Dialogue:" in text
    assert "你好" in text
    assert "世界" in text


def test_t3_cli_propagates_speech2srt_exit_code_3_auth_error(
    tmp_path, monkeypatch,
):
    """T3 #7: speech2srt exit 3 (auth) → main() returns 3."""
    seg_mp4, bv_dir, speech_wav = _setup_subtitle_cli_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "video2yt.subtitle_cli.subprocess.run",
        lambda argv, **kw: subprocess.CompletedProcess(
            args=argv, returncode=3, stdout="", stderr="auth failed",
        ),
    )
    rc = subtitle_cli.main([str(seg_mp4)])
    assert rc == 3


def test_t3_cli_propagates_speech2srt_exit_code_4_quota_error(
    tmp_path, monkeypatch,
):
    """T3 #8: speech2srt exit 4 (quota) → main() returns 4."""
    seg_mp4, bv_dir, speech_wav = _setup_subtitle_cli_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "video2yt.subtitle_cli.subprocess.run",
        lambda argv, **kw: subprocess.CompletedProcess(
            args=argv, returncode=4, stdout="", stderr="quota exceeded",
        ),
    )
    rc = subtitle_cli.main([str(seg_mp4)])
    assert rc == 4


def test_t3_cli_preflight_checks_speech2srt_on_path(monkeypatch):
    """T3 #9: speech2srt missing from PATH → preflight RuntimeError → exit 1."""
    def which(cmd):
        return "/usr/bin/found" if cmd in ("ffmpeg", "ffprobe") else None
    monkeypatch.setattr("video2yt.subtitle_cli.shutil.which", which)
    rc = subtitle_cli.main(["nonexistent.mp4"])
    assert rc == 1


def test_t3_cli_no_preview_burn_skips_ffmpeg_burn(tmp_path, monkeypatch):
    """T3 #11: --no-preview-burn flag is accepted; only ONE subprocess.run
    call happens (the speech2srt one — no separate ffmpeg burn invocation).
    T3 dropped the preview-burn entirely; this test guards against
    regression that adds a second subprocess."""
    seg_mp4, bv_dir, speech_wav = _setup_subtitle_cli_fixture(tmp_path, monkeypatch)
    captured: list[list[str]] = []

    def capture(argv, **kwargs):
        captured.append(list(argv))
        out_idx = argv.index("-o")
        Path(argv[out_idx + 1]).write_text(_FAKE_SRT, encoding="utf-8")
        return subprocess.CompletedProcess(args=argv, returncode=0,
                                           stdout="", stderr="")
    monkeypatch.setattr("video2yt.subtitle_cli.subprocess.run", capture)

    args = subtitle_cli.parse_args([str(seg_mp4), "--no-preview-burn"])
    subtitle_cli.run(args)

    assert len(captured) == 1
    assert captured[0][0] == "speech2srt"


def test_t3_cli_errors_when_speech2srt_writes_no_srt(tmp_path, monkeypatch):
    """T3 defensive: speech2srt exits 0 but the -o file is missing → raise.
    Prevents silent ASS-from-empty-SRT downstream."""
    seg_mp4, bv_dir, speech_wav = _setup_subtitle_cli_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "video2yt.subtitle_cli.subprocess.run",
        lambda argv, **kw: subprocess.CompletedProcess(
            args=argv, returncode=0, stdout="", stderr="",
        ),
    )
    args = subtitle_cli.parse_args([str(seg_mp4)])
    with pytest.raises(RuntimeError, match="speech2srt exited 0 but"):
        subtitle_cli.run(args)


def test_t3_cli_errors_when_speech2srt_writes_malformed_srt(
    tmp_path, monkeypatch,
):
    """T3 defensive: speech2srt exits 0 and writes the file, but the SRT
    is empty / has no parseable dialogue blocks → compose.srt_to_ass raises
    ValueError, mapped to exit 2."""
    seg_mp4, bv_dir, speech_wav = _setup_subtitle_cli_fixture(tmp_path, monkeypatch)
    def write_empty(argv, **kwargs):
        out_idx = argv.index("-o")
        Path(argv[out_idx + 1]).write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(args=argv, returncode=0,
                                           stdout="", stderr="")
    monkeypatch.setattr("video2yt.subtitle_cli.subprocess.run", write_empty)

    rc = subtitle_cli.main([str(seg_mp4)])
    assert rc == 2


def test_t3_cli_explicit_missing_context_file_exits_2(tmp_path, monkeypatch):
    """T3 wiring: a missing --context-file PATH propagates from the helper
    through run() → main() returns exit 2 (FileNotFoundError mapping)."""
    seg_mp4, bv_dir, speech_wav = _setup_subtitle_cli_fixture(tmp_path, monkeypatch)
    missing_ctx = tmp_path / "nope.txt"

    rc = subtitle_cli.main([str(seg_mp4), "--context-file", str(missing_ctx)])
    assert rc == 2


def test_t3_cli_emits_warning_when_no_context_file_and_cleanup_on(
    tmp_path, monkeypatch, capsys,
):
    """T3: no --context-file + --cleanup default → stderr warning;
    speech2srt argv has --cleanup but no --context-file."""
    seg_mp4, bv_dir, speech_wav = _setup_subtitle_cli_fixture(tmp_path, monkeypatch)
    captured: list[list[str]] = []

    def capture(argv, **kwargs):
        captured.append(list(argv))
        out_idx = argv.index("-o")
        Path(argv[out_idx + 1]).write_text(_FAKE_SRT, encoding="utf-8")
        return subprocess.CompletedProcess(args=argv, returncode=0,
                                           stdout="", stderr="")
    monkeypatch.setattr("video2yt.subtitle_cli.subprocess.run", capture)

    args = subtitle_cli.parse_args([str(seg_mp4)])
    subtitle_cli.run(args)

    err = capsys.readouterr().err
    assert "no --context-file" in err.lower() or "without context" in err.lower() \
        or "WARNING" in err
    argv = captured[0]
    assert "--cleanup" in argv
    assert "--context-file" not in argv


# ---------------------------------------------------------------------------
# T2 (speech2srt integration): per-project --context-file flag + resolver.
# ---------------------------------------------------------------------------


def test_t2_parse_args_accepts_context_file_flag(tmp_path):
    """T2 test: subtitle_cli accepts --context-file PATH (no parsing error)."""
    ctx = tmp_path / "ctx.txt"
    ctx.write_text("...", encoding="utf-8")
    args = subtitle_cli.parse_args(["seg.mp4", "--context-file", str(ctx)])
    assert args.context_file == ctx


def test_t2_parse_args_context_file_defaults_to_none():
    """T2 test: when --context-file omitted, args.context_file is None."""
    args = subtitle_cli.parse_args(["seg.mp4"])
    assert args.context_file is None


def test_t2_resolve_context_file_returns_explicit_path_no_warning(tmp_path):
    """T2 test: explicit context-file present → (path, False) — no warning."""
    ctx = tmp_path / "ctx.txt"
    ctx.write_text("hello", encoding="utf-8")
    resolved, warn = subtitle_cli._resolve_context_file(
        context_file=ctx, skip_cleanup=False,
    )
    assert resolved == ctx
    assert warn is False


def test_t2_resolve_context_file_raises_when_explicit_path_missing(tmp_path):
    """T2 test: explicit --context-file pointing at non-existent file →
    FileNotFoundError. main() converts that to exit 2."""
    missing = tmp_path / "does_not_exist.txt"
    with pytest.raises(FileNotFoundError, match="context file not found"):
        subtitle_cli._resolve_context_file(
            context_file=missing, skip_cleanup=False,
        )


def test_t2_resolve_context_file_returns_none_with_warning_when_cleanup_on_and_no_path():
    """T2 test: no --context-file + --cleanup on → (None, True) — emit warning."""
    resolved, warn = subtitle_cli._resolve_context_file(
        context_file=None, skip_cleanup=False,
    )
    assert resolved is None
    assert warn is True


def test_t2_resolve_context_file_returns_none_no_warning_when_skip_cleanup():
    """T2 test: --skip-cleanup short-circuits — no resolution, no warning,
    regardless of whether context_file was provided."""
    resolved, warn = subtitle_cli._resolve_context_file(
        context_file=None, skip_cleanup=True,
    )
    assert resolved is None
    assert warn is False


def test_t2_resolve_context_file_skip_cleanup_overrides_explicit_path(tmp_path):
    """T2 test: even with explicit --context-file, --skip-cleanup wins —
    no context goes to speech2srt because --cleanup itself is dropped."""
    ctx = tmp_path / "ctx.txt"
    ctx.write_text("hello", encoding="utf-8")
    resolved, warn = subtitle_cli._resolve_context_file(
        context_file=ctx, skip_cleanup=True,
    )
    assert resolved is None
    assert warn is False
