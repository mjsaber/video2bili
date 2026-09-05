"""Tests for the dynamic intro composer (video2yt.intro_compose).

Pure logic (SRT parse, normalize, card-timeline resolve, filtergraph string) is
tested directly; render() is tested with validate.probe + subprocess.run +
resolve_font mocked, so no ffmpeg/font dependency.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from video2yt import compose, intro_compose
from video2yt.intro_compose import (
    CardSpec,
    ResolvedCard,
    normalize_text,
    parse_cards_file,
    parse_srt_blocks,
    resolve_cards,
)

# A trimmed handfish-shaped SRT: the 4 cards first appear in blocks 2,4,7,10.
HANDFISH_SRT = """1
00:00:00,291 --> 00:00:04,794
大家好，今天教大家新賽季高端局必學的手牌魚。

2
00:00:04,794 --> 00:00:14,027
核心是這版本最新的大飾品『雙重縫針』。

3
00:00:14,027 --> 00:00:18,980
重點是搭配『讓友方目標法術施放兩次』的巴琳達‧石爐，

4
00:00:22,583 --> 00:00:24,159
前期用裁膾魚人，

5
00:00:30,239 --> 00:00:36,319
最後讓六本的魚人合唱團一波帶走全場。
"""

CARDS = [
    CardSpec("double_stitch_needle.png", "雙重縫針"),
    CardSpec("balinda.png", "巴琳達‧石爐"),
    CardSpec("butchering.png", "裁膾"),
    CardSpec("choral.png", "魚人合唱團"),
]


def _touch_cards(tmp_path: Path, names) -> Path:
    for n in names:
        (tmp_path / n).write_bytes(b"x")
    return tmp_path


# ---- SRT parsing -----------------------------------------------------------
def test_parse_srt_blocks_times_and_text():
    blocks = parse_srt_blocks(HANDFISH_SRT)
    assert len(blocks) == 5
    assert blocks[0].start == pytest.approx(0.291)
    assert blocks[1].start == pytest.approx(4.794)
    assert "雙重縫針" in blocks[1].text


def test_parse_srt_blocks_skips_garbage():
    assert parse_srt_blocks("not an srt\n\nstill not") == []


# ---- normalize -------------------------------------------------------------
def test_normalize_strips_quotes_and_punct():
    assert normalize_text("『雙重縫針』——") == "雙重縫針"
    assert normalize_text("巴琳達‧石爐，") == "巴琳達石爐"


# ---- cards file parsing ----------------------------------------------------
def test_parse_cards_file_basic(tmp_path):
    f = tmp_path / "cards.txt"
    f.write_text(
        "# comment\n"
        "a.png | 雙重縫針\n"
        "\n"
        "b.png | 巴琳達 | 14.0 22.5\n",
        encoding="utf-8",
    )
    specs = parse_cards_file(f)
    assert [s.name for s in specs] == ["雙重縫針", "巴琳達"]
    assert specs[0].start is None
    assert specs[1].start == 14.0 and specs[1].end == 22.5


def test_parse_cards_file_rejects_malformed(tmp_path):
    f = tmp_path / "cards.txt"
    f.write_text("only_one_field\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected"):
        parse_cards_file(f)


def test_parse_cards_file_rejects_empty(tmp_path):
    f = tmp_path / "cards.txt"
    f.write_text("# just a comment\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no card entries"):
        parse_cards_file(f)


# ---- resolve_cards ---------------------------------------------------------
def test_resolve_cards_handfish(tmp_path):
    _touch_cards(tmp_path, [c.png for c in CARDS])
    blocks = parse_srt_blocks(HANDFISH_SRT)
    resolved = resolve_cards(CARDS, blocks, duration=44.496, cards_dir=tmp_path)

    # seams are frame-quantized (1/30s): 14.027->14.033, 22.583->22.567, 30.239->30.233
    assert [round(c.display_start, 3) for c in resolved] == [0.0, 14.033, 22.567, 30.233]
    # last end is the exact audio duration (unquantized)
    assert [round(c.display_end, 3) for c in resolved] == [14.033, 22.567, 30.233, 44.496]
    # first card: lead-in from 0, no fade; others fade
    assert resolved[0].fade is False
    assert all(c.fade for c in resolved[1:])
    # strictly increasing starts
    starts = [c.display_start for c in resolved]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)


def test_resolve_cards_quantizes_to_frame(tmp_path):
    _touch_cards(tmp_path, [c.png for c in CARDS])
    blocks = parse_srt_blocks(HANDFISH_SRT)
    resolved = resolve_cards(CARDS, blocks, duration=44.496, cards_dir=tmp_path)
    # all display starts land on a 1/30s frame (so seams are frame-exact)
    for c in resolved:
        assert c.display_start == pytest.approx(round(c.display_start * 30) / 30)
    # intermediate ends are frame-snapped; the last end is the exact duration
    for c in resolved[:-1]:
        assert c.display_end == pytest.approx(round(c.display_end * 30) / 30)
    assert resolved[-1].display_end == pytest.approx(44.496)


def test_resolve_cards_forward_cursor(tmp_path):
    # 雙重縫針 appears in block 2; a teaser "雙重縫針" earlier must not let a
    # later card steal an earlier slot. Here the 2nd card's name also appears
    # only after the 1st — cursor advances past block 2.
    _touch_cards(tmp_path, ["a.png", "b.png"])
    srt = (
        "1\n00:00:00,000 --> 00:00:05,000\n先講雙重縫針再說別的。\n\n"
        "2\n00:00:05,000 --> 00:00:10,000\n然後是巴琳達‧石爐登場。\n"
    )
    specs = [CardSpec("a.png", "雙重縫針"), CardSpec("b.png", "巴琳達‧石爐")]
    resolved = resolve_cards(specs, parse_srt_blocks(srt), 10.0, tmp_path)
    assert resolved[0].display_start == 0.0       # lead-in
    assert resolved[1].display_start == pytest.approx(5.0)


def test_resolve_cards_no_match_raises(tmp_path):
    _touch_cards(tmp_path, ["a.png"])
    specs = [CardSpec("a.png", "不存在的卡")]
    with pytest.raises(ValueError, match="not found in the SRT"):
        resolve_cards(specs, parse_srt_blocks(HANDFISH_SRT), 44.496, tmp_path)


def test_resolve_cards_explicit_time_override(tmp_path):
    _touch_cards(tmp_path, ["a.png", "b.png"])
    specs = [
        CardSpec("a.png", "雙重縫針"),
        CardSpec("b.png", "魚人合唱團", start=30.0, end=44.0),
    ]
    resolved = resolve_cards(specs, parse_srt_blocks(HANDFISH_SRT), 44.496, tmp_path)
    assert resolved[1].display_start == pytest.approx(30.0)
    assert resolved[1].display_end == pytest.approx(44.0)


def test_resolve_cards_explicit_out_of_range_raises(tmp_path):
    _touch_cards(tmp_path, ["a.png"])
    specs = [CardSpec("a.png", "雙重縫針", start=40.0, end=99.0)]
    with pytest.raises(ValueError, match="invalid"):
        resolve_cards(specs, parse_srt_blocks(HANDFISH_SRT), 44.496, tmp_path)


def test_resolve_cards_non_increasing_raises(tmp_path):
    _touch_cards(tmp_path, ["a.png", "b.png"])
    # two explicit cards with decreasing starts
    specs = [
        CardSpec("a.png", "雙重縫針", start=20.0, end=30.0),
        CardSpec("b.png", "巴琳達‧石爐", start=10.0, end=15.0),
    ]
    with pytest.raises(ValueError, match="strictly increasing|invalid"):
        resolve_cards(specs, parse_srt_blocks(HANDFISH_SRT), 44.496, tmp_path)


def test_resolve_cards_missing_png_raises(tmp_path):
    # name matches but the image file doesn't exist
    specs = [CardSpec("missing.png", "雙重縫針")]
    with pytest.raises(FileNotFoundError):
        resolve_cards(specs, parse_srt_blocks(HANDFISH_SRT), 44.496, tmp_path)


# ---- srt_to_ass margin + max_lines extensions ------------------------------
def test_srt_to_ass_writes_custom_margins():
    ass = compose.srt_to_ass(
        "1\n00:00:00,000 --> 00:00:02,000\n短句\n",
        1920, 1080, "Hiragino Sans GB", 46,
        position="bottom", margin_l=80, margin_r=680, margin_v=70,
    )
    # Style line ends with ...,Alignment,MarginL,MarginR,MarginV,Encoding
    assert ",80,680,70,1" in ass


def test_srt_to_ass_caps_lines(capsys):
    long_line = "核" * 60  # forces >2 wrapped lines at font 46 / margin 680
    ass = compose.srt_to_ass(
        f"1\n00:00:00,000 --> 00:00:02,000\n{long_line}\n",
        1920, 1080, "Hiragino Sans GB", 46,
        position="bottom", margin_l=80, margin_r=680, margin_v=70,
        max_lines=2,
    )
    dialogue = [l for l in ass.splitlines() if l.startswith("Dialogue:")][0]
    # at most 2 rendered lines -> at most one hard break
    assert dialogue.count("\\N") == 1
    assert "warning" in capsys.readouterr().err


def test_srt_to_ass_bold_sets_ass_bold_flag():
    block = "1\n00:00:00,000 --> 00:00:02,000\n句\n"
    plain = compose.srt_to_ass(block, 1920, 1080, "Hiragino Sans GB", 54, position="bottom")
    bold = compose.srt_to_ass(block, 1920, 1080, "Hiragino Sans GB", 54, position="bottom", bold=True)
    style_of = lambda a: [l for l in a.splitlines() if l.startswith("Style:")][0]
    assert "0,0,0,0,100,100," in style_of(plain)    # Bold=0
    assert "-1,0,0,0,100,100," in style_of(bold)     # Bold=-1 (ASS true)


# ---- filtergraph string ----------------------------------------------------
def _two_cards(tmp_path):
    _touch_cards(tmp_path, ["a.png", "b.png"])
    return [
        ResolvedCard(tmp_path / "a.png", "雙重縫針", 0.0, 14.027, fade=False),
        ResolvedCard(tmp_path / "b.png", "巴琳達‧石爐", 14.027, 44.496, fade=True),
    ]


def test_build_filter_codex_fixes(tmp_path):
    cards = _two_cards(tmp_path)
    f = intro_compose._build_filter(cards, n_inputs_before_cards=2, font="/F.ttc")
    # mascot rotate bounded (no clipping)
    assert "rotw(0.045)" in f and "roth(0.045)" in f
    # half-open gates with plain commas inside enable quotes
    assert "enable='gte(t,0.000)*lt(t,14.027)'" in f
    assert "enable='gte(t,14.027)*lt(t,44.496)'" in f
    # first card NO fade, second card fades -> exactly one fade=t=in
    assert f.count("fade=t=in") == 1
    # subtitle referenced by basename
    assert "subtitles=f='_intro.sub.ass'" in f
    # no scrim by default -> cards overlay straight onto bg0
    assert "[bgs]" not in f
    assert "[bg0][card0]" in f


def test_build_filter_omits_title_and_captions_by_default(tmp_path):
    cards = _two_cards(tmp_path)
    f = intro_compose._build_filter(cards, n_inputs_before_cards=2, font="/F.ttc")
    # no top title (show_title defaults False) and no per-card name captions
    assert "drawtext" not in f
    assert "_title.txt" not in f
    assert "_card" not in f
    assert "0xFFD400" not in f  # the old gold caption colour is gone


def test_build_filter_title_when_requested(tmp_path):
    cards = _two_cards(tmp_path)
    f = intro_compose._build_filter(
        cards, n_inputs_before_cards=2, font="/F.ttc", show_title=True
    )
    assert "textfile='_title.txt':expansion=none" in f
    assert "fontfile='/F.ttc'" in f


def test_build_filter_with_scrim(tmp_path):
    cards = _two_cards(tmp_path)
    f = intro_compose._build_filter(
        cards, n_inputs_before_cards=2, font="/F.ttc", scrim_idx=4
    )
    # scrim overlaid on the bg, and cards overlay onto the scrimmed bg
    assert "[bg0][4:v]overlay=0:0[bgs]" in f
    assert "[bgs][card0]" in f


# ---- render (ffmpeg mocked) ------------------------------------------------
def test_render_builds_correct_command(tmp_path, monkeypatch):
    # inputs
    (tmp_path / "audio.mp3").write_bytes(b"x")
    (tmp_path / "bg.png").write_bytes(b"x")
    (tmp_path / "srt.srt").write_text(HANDFISH_SRT, encoding="utf-8")
    (tmp_path / "mascot.png").write_bytes(b"x")
    _touch_cards(tmp_path, [c.png for c in CARDS])
    cards_file = tmp_path / "cards.txt"
    cards_file.write_text(
        "".join(f"{c.png} | {c.name}\n" for c in CARDS), encoding="utf-8"
    )

    monkeypatch.setattr(
        intro_compose.validate, "probe",
        lambda p: SimpleNamespace(duration=44.496),
    )
    monkeypatch.setattr(intro_compose, "resolve_font", lambda: "/F.ttc")

    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["cwd"] = kw.get("cwd")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(intro_compose.subprocess, "run", fake_run)

    out_dir = tmp_path / "out"
    inputs = intro_compose.IntroInputs(
        audio=tmp_path / "audio.mp3",
        bg=tmp_path / "bg.png",
        srt=tmp_path / "srt.srt",
        cards_file=cards_file,
        mascot=tmp_path / "mascot.png",
        title="「測試」標題",
        cards_dir=tmp_path,
        scrim=None,  # isolate the count assertions from the optional scrim
    )
    result = intro_compose.render(inputs, out_dir / "intro.mp4")
    cmd = captured["cmd"]

    assert cmd[0] == "ffmpeg"
    # one -framerate 30 -loop 1 per image input: bg + mascot + 4 cards = 6
    assert cmd.count("-framerate") == 6
    assert cmd.count("-loop") == 6
    # every -framerate is immediately followed by 30 then -loop 1
    for i, tok in enumerate(cmd):
        if tok == "-framerate":
            assert cmd[i + 1] == "30"
            assert cmd[i + 2] == "-loop" and cmd[i + 3] == "1"
    # audio is the last -i, mapped as input index 6
    assert "[outv]" in cmd
    assert f"{2 + len(CARDS)}:a" in cmd
    # dynamic-text + ASS files written next to the output
    assert (out_dir / "_title.txt").read_text(encoding="utf-8") == "「測試」標題"
    assert not (out_dir / "_card0.txt").exists()  # card names are no longer drawn
    assert (out_dir / "_intro.sub.ass").exists()
    assert result == out_dir / "intro.mp4"
    assert captured["cwd"] == out_dir


@pytest.mark.parametrize("style,use_scrim", [("warm-tavern", True), ("anime-sketch", False)])
def test_render_includes_scrim_only_for_legacy_theme(tmp_path, monkeypatch, style, use_scrim):
    for n in ("audio.mp3", "bg.png", "mascot.png", "scrim.png"):
        (tmp_path / n).write_bytes(b"x")
    (tmp_path / "srt.srt").write_text(HANDFISH_SRT, encoding="utf-8")
    _touch_cards(tmp_path, [c.png for c in CARDS])
    cards_file = tmp_path / "cards.txt"
    cards_file.write_text(
        "".join(f"{c.png} | {c.name}\n" for c in CARDS), encoding="utf-8"
    )
    monkeypatch.setattr(
        intro_compose.validate, "probe", lambda p: SimpleNamespace(duration=44.496)
    )
    monkeypatch.setattr(intro_compose, "resolve_font", lambda: "/F.ttc")
    captured = {}
    monkeypatch.setattr(
        intro_compose.subprocess, "run",
        lambda cmd, **kw: captured.update(cmd=cmd) or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    inputs = intro_compose.IntroInputs(
        audio=tmp_path / "audio.mp3", bg=tmp_path / "bg.png",
        srt=tmp_path / "srt.srt", cards_file=cards_file,
        mascot=tmp_path / "mascot.png", title="T", cards_dir=tmp_path,
        scrim=tmp_path / "scrim.png", style=style,
    )
    intro_compose.render(inputs, tmp_path / "out" / "intro.mp4")
    cmd = captured["cmd"]

    # bg + mascot + 4 cards + scrim = 7 looped image inputs
    assert cmd.count("-framerate") == 6 + int(use_scrim)
    fc = cmd[cmd.index("-filter_complex") + 1]
    # scrim (input index 6) overlaid on bg; audio is input index 7
    assert ("[bg0][6:v]overlay=0:0[bgs]" in fc) == use_scrim
    assert f"{2 + len(CARDS) + int(use_scrim)}:a" in cmd
