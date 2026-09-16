"""video2yt-short: vertical Short cut with claim/label overlays, subtitles and outro."""
import shutil
import subprocess
from pathlib import Path

import pytest

from video2yt import short, short_cli, validate
from video2yt.validate import MediaInfo


SRT = """1
00:00:10,000 --> 00:00:12,000
第一句

2
00:00:11,500 --> 00:00:15,000
跨過起點的句子

3
00:00:20,000 --> 00:00:21,000
窗口之外
"""


def test_shift_srt_keeps_overlapping_blocks_rebased_and_clamped():
    blocks = short.shift_srt(SRT, 11.0, 14.0)
    assert [(b.start, b.end, b.text) for b in blocks] == [
        (0.0, 1.0, "第一句"),
        (0.5, 3.0, "跨過起點的句子"),
    ]


def test_blocks_to_srt_round_trips():
    blocks = short.shift_srt(SRT, 11.0, 14.0)
    assert short.blocks_to_srt(blocks).startswith("1\n00:00:00,000 --> 00:00:01,000\n第一句\n\n2\n")


@pytest.mark.parametrize("text", ["600:120:1060", "a:b:c:d", "0:0:0:10", "-1:0:10:10"])
def test_rect_parse_rejects_bad_input(text):
    with pytest.raises(ValueError):
        short.Rect.parse(text)


def test_rect_must_fit_source():
    with pytest.raises(ValueError, match="exceeds"):
        short.Rect.parse("1000:0:1000:100").check_within(1920, 1080, "board")


@pytest.fixture
def fake_media(tmp_path, monkeypatch):
    video = tmp_path / "src 中文.mp4"; video.write_bytes(b"v")
    bg = tmp_path / "bg.png"; bg.write_bytes(b"p")
    mascot = tmp_path / "mascot.png"; mascot.write_bytes(b"m")
    font = tmp_path / "font.ttc"; font.write_bytes(b"f")
    infos = {
        str(video.resolve()): MediaInfo(60.0, 1920, 1080, True, True, "h264", "aac", 1),
    }
    def probe(path: Path):
        key = str(Path(path).resolve())
        if key in infos:
            return infos[key]
        return MediaInfo(clip_plus_outro[0], 1080, 1920, True, True, "h264", "aac", 1)
    clip_plus_outro = [0.0]
    monkeypatch.setattr(short.validate, "probe", probe)
    return video, bg, mascot, font, clip_plus_outro


def _kw(bg, mascot, font, **over):
    base = dict(claim="第9回合 全隊破萬", comp="海盜倒轉", rank="這局第1名", bg=bg, mascot=mascot, font=font)
    base.update(over)
    return base


@pytest.mark.parametrize("start,end,outro", [(10, 10, 4), (-1, 5, 4), (0, 176, 4), (0, 5, 0.5)])
def test_rejects_bad_windows(fake_media, tmp_path, start, end, outro):
    video, bg, mascot, font, _ = fake_media
    with pytest.raises(ValueError):
        short.render(video, [(start, end)], tmp_path / "o.mp4", outro_seconds=outro, **_kw(bg, mascot, font))


@pytest.mark.parametrize("field,value", [
    ("claim", "這一行實在太長了超過十四個字元限制"), ("claim", "一\n二\n三"), ("comp", ""), ("rank", "a\tb"),
    ("cta_text", "x" * 13), ("cta_text", "a\nb\nc"), ("link_text", "y" * 21),
])
def test_rejects_bad_text(fake_media, tmp_path, field, value):
    video, bg, mascot, font, _ = fake_media
    with pytest.raises(ValueError):
        short.render(video, [(0, 5)], tmp_path / "o.mp4", **_kw(bg, mascot, font, **{field: value}))


def test_rejects_non_1080p_source(fake_media, tmp_path, monkeypatch):
    video, bg, mascot, font, _ = fake_media
    monkeypatch.setattr(short.validate, "probe", lambda p: MediaInfo(60.0, 1280, 720, True, True, "h264", "aac", 1))
    with pytest.raises(ValueError, match="1920x1080"):
        short.render(video, [(0, 5)], tmp_path / "o.mp4", **_kw(bg, mascot, font))


def test_rejects_end_past_source(fake_media, tmp_path):
    video, bg, mascot, font, _ = fake_media
    with pytest.raises(ValueError, match="exceeds source duration"):
        short.render(video, [(50, 70)], tmp_path / "o.mp4", **_kw(bg, mascot, font))


def test_command_uses_textfiles_and_shifted_subtitles(fake_media, tmp_path, monkeypatch):
    video, bg, mascot, font, clip_plus_outro = fake_media
    srt = tmp_path / "speech.srt"; srt.write_text(SRT, encoding="utf-8")
    captured = {}
    def fake_run(cmd, cwd, **kw):
        captured["cmd"] = cmd
        captured["files"] = {p.name: p.read_text(encoding="utf-8") for p in Path(cwd).glob("*.txt")}
        captured["ass"] = (Path(cwd) / "subs.ass").read_text(encoding="utf-8")
        (Path(cwd) / "rendered.mp4").write_bytes(b"out")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(short.subprocess, "run", fake_run)
    clip_plus_outro[0] = 3.0 + 4.0
    out = tmp_path / "s.mp4"
    claim = "5% 的'機率\n它做到了"
    short.render(video, [(11.0, 14.0)], out, srt=srt, face=short.Rect(1400, 760, 500, 300), hook_seconds=0,
                 **_kw(bg, mascot, font, claim=claim))
    cmd = captured["cmd"]
    assert out.read_bytes() == b"out"
    assert cmd[cmd.index("-ss") + 1] == "11.000" and cmd[cmd.index("-t") + 1] == "3.000"
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert claim not in graph and "海盜倒轉" not in graph
    assert "textfile=claim.txt" in graph and "textfile=label.txt" in graph
    assert "crop=500:300:1400:760" in graph and "subtitles=f='subs.ass'" in graph
    assert "concat=n=2:v=1:a=1" in graph and "trim=start=0.000:end=3.000" in graph
    assert "textfile=arrow.txt" in graph and captured["files"]["arrow.txt"] == "↙"
    assert "y=H-h-400[o1]" in graph
    assert captured["files"]["claim.txt"] == claim
    assert captured["files"]["label.txt"] == "海盜倒轉｜這局第1名"
    assert "0:00:00.50,0:00:03.00" in captured["ass"] and "窗口之外" not in captured["ass"]


def test_no_face_uses_mascot_panel_inputs(fake_media, tmp_path, monkeypatch):
    video, bg, mascot, font, clip_plus_outro = fake_media
    captured = {}
    def fake_run(cmd, cwd, **kw):
        captured["cmd"] = cmd
        (Path(cwd) / "rendered.mp4").write_bytes(b"out")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(short.subprocess, "run", fake_run)
    clip_plus_outro[0] = 5.0
    short.render(video, [(0, 5)], tmp_path / "s.mp4", outro_seconds=0, **_kw(bg, mascot, font))
    cmd = captured["cmd"]
    assert cmd.count(str(mascot.resolve())) == 1 and cmd.count(str(bg.resolve())) == 1
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "[1:v]" in graph and "[2:v]" in graph and "[outro]" not in graph and "anullsrc" not in " ".join(cmd)


def test_output_validation_failure_leaves_no_output(fake_media, tmp_path, monkeypatch):
    video, bg, mascot, font, clip_plus_outro = fake_media
    def fake_run(cmd, cwd, **kw):
        (Path(cwd) / "rendered.mp4").write_bytes(b"out")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(short.subprocess, "run", fake_run)
    clip_plus_outro[0] = 2.0  # expected 9.0
    out = tmp_path / "s.mp4"
    with pytest.raises(ValueError, match="duration"):
        short.render(video, [(0, 5)], out, **_kw(bg, mascot, font))
    assert not out.exists()


def test_cli_parses_times_and_newline_claim(monkeypatch):
    seen = {}
    monkeypatch.setattr(short_cli.short, "render", lambda *a, **k: seen.update(a=a, k=k) or Path("x.mp4"))
    args = short_cli.parse_args(["--video", "v.mp4", "--start", "1:05", "--end", "2:00", "--claim", "上\\n下",
                                 "--comp", "海盜", "--rank", "第1名", "--face", "1:2:3:4", "-o", "s.mp4"])
    short_cli.run(args)
    assert seen["a"][1] == [(65.0, 120.0)]
    assert seen["k"]["claim"] == "上\n下" and seen["k"]["face"] == short.Rect(1, 2, 3, 4)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg required")
def test_real_render_produces_vertical_short_with_outro(tmp_path):
    from PIL import Image
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "6",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
    bg = tmp_path / "bg.png"; Image.new("RGB", (640, 1138), (250, 245, 230)).save(bg)
    mascot = tmp_path / "m.png"; Image.new("RGBA", (200, 300), (200, 120, 90, 255)).save(mascot)
    srt = tmp_path / "s.srt"; srt.write_text("1\n00:00:01,000 --> 00:00:03,000\n測試字幕\n", encoding="utf-8")
    out = tmp_path / "short.mp4"
    try:
        short.render(src, [(1.0, 2.5), (4.0, 5.0)], out, claim="第9回合\n全隊破萬", comp="海盜倒轉", rank="這局第1名",
                     srt=srt, outro_seconds=1.5, bg=bg, mascot=mascot)
    except RuntimeError as exc:  # no CJK font on this machine
        pytest.skip(str(exc))
    info = validate.probe(out)
    assert (info.width, info.height) == (1080, 1920)
    assert info.has_audio and abs(info.duration - 4.0) < 0.35


def test_multi_range_concats_and_offsets_subtitles(fake_media, tmp_path, monkeypatch):
    video, bg, mascot, font, clip_plus_outro = fake_media
    srt = tmp_path / "speech.srt"; srt.write_text(SRT, encoding="utf-8")
    captured = {}
    def fake_run(cmd, cwd, **kw):
        captured["cmd"] = cmd
        captured["ass"] = (Path(cwd) / "subs.ass").read_text(encoding="utf-8")
        (Path(cwd) / "rendered.mp4").write_bytes(b"out")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(short.subprocess, "run", fake_run)
    clip_plus_outro[0] = (2.0 + 1.5) + 4.0
    short.render(video, [(10.0, 12.0), (20.0, 21.5)], tmp_path / "s.mp4", srt=srt, hook_seconds=0, **_kw(bg, mascot, font))
    cmd = captured["cmd"]
    assert cmd[cmd.index("-ss") + 1] == "10.000" and cmd[cmd.index("-t") + 1] == "11.500"
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "trim=start=0.000:end=2.000" in graph and "trim=start=10.000:end=11.500" in graph
    assert "concat=n=2:v=1:a=1[clipv][clipa0]" in graph
    # 第一句 10-12 → 0-2 ; 窗口之外 20-21 → offset 2.0 → 2.0-3.0
    assert "0:00:00.00,0:00:02.00" in captured["ass"] and "0:00:02.00,0:00:03.00" in captured["ass"]


def test_ranges_must_be_ordered(fake_media, tmp_path):
    video, bg, mascot, font, _ = fake_media
    with pytest.raises(ValueError, match="after the previous"):
        short.render(video, [(10.0, 12.0), (11.0, 13.0)], tmp_path / "o.mp4", **_kw(bg, mascot, font))


def test_cli_range_flag(monkeypatch):
    seen = {}
    monkeypatch.setattr(short_cli.short, "render", lambda *a, **k: seen.update(a=a) or Path("x.mp4"))
    args = short_cli.parse_args(["--video", "v.mp4", "--range", "19:48~21:57", "--range", "22:02~1324.3",
                                 "--claim", "x", "--comp", "y", "--rank", "z", "-o", "s.mp4"])
    short_cli.run(args)
    assert seen["a"][1] == [(1188.0, 1317.0), (1322.0, 1324.3)]


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg required")
def test_real_render_mascot_panel_without_outro(tmp_path):
    from PIL import Image
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
    bg = tmp_path / "bg.png"; Image.new("RGB", (640, 1138), (250, 245, 230)).save(bg)
    mascot = tmp_path / "m.png"; Image.new("RGBA", (200, 300), (200, 120, 90, 255)).save(mascot)
    out = tmp_path / "short.mp4"
    try:
        short.render(src, [(0.5, 2.5)], out, claim="全隊破萬", comp="海盜倒轉", rank="這局第1名",
                     outro_seconds=0, bg=bg, mascot=mascot)
    except RuntimeError as exc:
        pytest.skip(str(exc))
    info = validate.probe(out)
    assert (info.width, info.height) == (1080, 1920) and info.has_audio and abs(info.duration - 2.0) < 0.35


def test_source_to_clip_time_maps_ranges_and_gaps():
    ranges = [(10.0, 20.0), (30.0, 35.0)]
    assert short.source_to_clip_time(ranges, 5.0) == 0.0
    assert short.source_to_clip_time(ranges, 15.0) == 5.0
    assert short.source_to_clip_time(ranges, 25.0) == 10.0   # gap snaps to next range start
    assert short.source_to_clip_time(ranges, 32.0) == 12.0
    assert short.source_to_clip_time(ranges, 99.0) == 15.0


def test_context_promise_and_stages_are_textfiles_with_gates(fake_media, tmp_path, monkeypatch):
    video, bg, mascot, font, clip_plus_outro = fake_media
    captured = {}
    def fake_run(cmd, cwd, **kw):
        captured["cmd"] = cmd
        captured["files"] = {p.name: p.read_text(encoding="utf-8") for p in Path(cwd).glob("*.txt")}
        (Path(cwd) / "rendered.mp4").write_bytes(b"out")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(short.subprocess, "run", fake_run)
    clip_plus_outro[0] = 15.0 + 4.0
    short.render(video, [(10.0, 20.0), (30.0, 35.0)], tmp_path / "s.mp4",
                 context="第14回合・剩2血", promise="90秒後破萬", stages=[("招募中", 10.0), ("開戰", 18.0), ("結算", 31.0)],
                 **_kw(bg, mascot, font))
    graph = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert captured["files"]["context.txt"] == "第14回合・剩2血" and captured["files"]["promise.txt"] == "90秒後破萬"
    assert captured["files"]["stage0.txt"] == "招募中" and captured["files"]["stage2.txt"] == "結算"
    assert "textfile=stage0.txt" in graph and "enable='gte(t,0.000)*lt(t,8.000)'" in graph
    assert "enable='gte(t,8.000)*lt(t,11.000)'" in graph and "enable='gte(t,11.000)*lt(t,15.000)'" in graph
    assert "textfile=context.txt" in graph and "textfile=promise.txt" in graph
    assert f"{short.CLAIM_Y}+60*max(0\\,1-max(0\\,t-0.00)/0.3)" in graph


@pytest.mark.parametrize("kw", [
    {"context": "x" * 21}, {"promise": "a\nb"}, {"stages": [("這個標籤太長了", 10.0)]},
    {"stages": [("招募", 10.0), ("開戰", 10.0)]},
])
def test_rejects_bad_context_promise_stage(fake_media, tmp_path, monkeypatch, kw):
    video, bg, mascot, font, _ = fake_media
    monkeypatch.setattr(short.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run")))
    with pytest.raises(ValueError):
        short.render(video, [(10.0, 20.0)], tmp_path / "o.mp4", **_kw(bg, mascot, font), **kw)


def test_cli_stage_flag(monkeypatch):
    seen = {}
    monkeypatch.setattr(short_cli.short, "render", lambda *a, **k: seen.update(k=k) or Path("x.mp4"))
    args = short_cli.parse_args(["--video", "v.mp4", "--range", "1:00~2:00", "--claim", "x", "--comp", "y", "--rank", "z",
                                 "--stage", "招募中@1:00", "--stage", "開戰@1:30", "--context", "c", "--promise", "p", "-o", "s.mp4"])
    short_cli.run(args)
    assert seen["k"]["stages"] == [("招募中", 60.0), ("開戰", 90.0)] and seen["k"]["context"] == "c"


ASS = """[Script Info]
PlayResX: 1920
PlayResY: 1080

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:05.00,0:00:09.00,Default,,0,0,0,,before window
Dialogue: 0,0:00:09.50,0:00:15.00,Default,,0,0,0,,{\\move(1920,50,-100,50)}straddles, keep
Dialogue: 0,0:00:12.00,0:00:20.00,Default,,0,0,0,,inside, keep
"""


def test_shift_ass_rebases_and_drops_past_lines():
    out = short.shift_ass(ASS, 10.0)
    assert "before window" not in out
    assert "Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,{\\move(1920,50,-100,50)}straddles, keep" in out
    assert "Dialogue: 0,0:00:02.00,0:00:10.00,Default,,0,0,0,,inside, keep" in out
    assert "PlayResX: 1920" in out


def test_sibling_danmaku_is_burned_before_crop_unless_disabled(fake_media, tmp_path, monkeypatch):
    video, bg, mascot, font, clip_plus_outro = fake_media
    video.with_name(video.stem + ".danmaku.ass").write_text(ASS, encoding="utf-8")
    captured = {}
    def fake_run(cmd, cwd, **kw):
        captured["cmd"] = cmd
        captured["ass"] = (Path(cwd) / "danmaku.ass").read_text(encoding="utf-8") if (Path(cwd) / "danmaku.ass").exists() else None
        (Path(cwd) / "rendered.mp4").write_bytes(b"out")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(short.subprocess, "run", fake_run)
    clip_plus_outro[0] = 5.0 + 4.0
    short.render(video, [(10.0, 15.0)], tmp_path / "s.mp4", **_kw(bg, mascot, font))
    graph = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    # .ass sibling: burned on the full frame before the crop, rows pushed down by board.y
    assert graph.startswith("[0:v]fps=30,subtitles=f='danmaku.ass',split=1")
    assert "0:00:00.00,0:00:05.00" in captured["ass"] and "before window" not in captured["ass"]
    assert "\\move(1920,170,-100,170)" in captured["ass"]   # 50 + board.y(120)
    short.render(video, [(10.0, 15.0)], tmp_path / "s2.mp4", auto_danmaku=False, **_kw(bg, mascot, font))
    assert "danmaku" not in captured["cmd"][captured["cmd"].index("-filter_complex") + 1] and captured["ass"] is None


def test_subtitles_are_pushed_past_the_hook_window(fake_media, tmp_path, monkeypatch):
    video, bg, mascot, font, clip_plus_outro = fake_media
    srt = tmp_path / "speech.srt"; srt.write_text(SRT, encoding="utf-8")
    captured = {}
    def fake_run(cmd, cwd, **kw):
        captured["ass"] = (Path(cwd) / "subs.ass").read_text(encoding="utf-8")
        (Path(cwd) / "rendered.mp4").write_bytes(b"out")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(short.subprocess, "run", fake_run)
    clip_plus_outro[0] = 6.0 + 4.0
    # 第一句 10-12 → 0-2 (entirely inside the 3s hook → dropped); 跨過起點 11.5-15 → 1.5-5 → clamped to 3-5
    short.render(video, [(10.0, 16.0)], tmp_path / "s.mp4", srt=srt, hook_seconds=3.0, **_kw(bg, mascot, font))
    assert "第一句" not in captured["ass"] and "0:00:03.00,0:00:05.00" in captured["ass"]


def test_offset_ass_y_shifts_move_and_pos():
    src = "{\\move(1920, 0, -350, 0)}a\n{\\pos(960,40)}b\n{\\an8}c"
    out = short.offset_ass_y(src, 90)
    assert "\\move(1920,90,-350,90)" in out and "\\pos(960,130)" in out and "{\\an8}c" in out


def test_xml_sibling_is_relaid_for_board_and_burned_after_crop(fake_media, tmp_path, monkeypatch):
    video, bg, mascot, font, clip_plus_outro = fake_media
    video.with_name(video.stem + ".danmaku.xml").write_bytes(b"<i></i>")
    video.with_name(video.stem + ".danmaku.ass").write_text(ASS, encoding="utf-8")  # xml wins
    seen = {}
    def fake_convert(xml_bytes, **kw):
        seen.update(kw)
        return ASS
    monkeypatch.setattr(short, "danmaku_ass_for_board", lambda b: fake_convert(b, stage_width=1080, stage_height=896))
    captured = {}
    def fake_run(cmd, cwd, **kw):
        captured["cmd"] = cmd
        captured["ass"] = (Path(cwd) / "danmaku.ass").read_text(encoding="utf-8")
        (Path(cwd) / "rendered.mp4").write_bytes(b"out")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(short.subprocess, "run", fake_run)
    clip_plus_outro[0] = 5.0 + 4.0
    short.render(video, [(10.0, 15.0)], tmp_path / "s.mp4", **_kw(bg, mascot, font))
    graph = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert seen == {"stage_width": 1080, "stage_height": 896}
    assert "[0:v]fps=30,split=1" in graph
    assert "scale=1080:896,setsar=1,subtitles=f='danmaku.ass'[board]" in graph
    assert "0:00:00.00,0:00:05.00" in captured["ass"] and "\\move(1920,160,-100,160)" in captured["ass"]  # 50 + top margin 110


def test_caption_band_draws_black_strip_and_moves_captions_into_it(fake_media, tmp_path, monkeypatch):
    video, bg, mascot, font, clip_plus_outro = fake_media
    srt = tmp_path / "speech.srt"; srt.write_text(SRT, encoding="utf-8")
    captured = {}
    def fake_run(cmd, cwd, **kw):
        captured["cmd"] = cmd
        captured["ass"] = (Path(cwd) / "subs.ass").read_text(encoding="utf-8")
        (Path(cwd) / "rendered.mp4").write_bytes(b"out")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(short.subprocess, "run", fake_run)
    clip_plus_outro[0] = 6.0 + 4.0
    short.render(video, [(10.0, 16.0)], tmp_path / "s.mp4", srt=srt, hook_seconds=0, caption_band=150,
                 face=short.Rect(1470, 790, 450, 290), **_kw(bg, mascot, font))
    graph = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert f"drawbox=x=0:y={short.TOP_H}:w=1080:h=150:color=black:t=fill" in graph
    assert graph.index("drawbox=") < graph.index("textfile=label.txt")
    # MarginV centres two 54px lines inside the 150px band: TOP_H + (150-116)//2 = TOP_H + 17
    assert f",{short.TOP_H + 17}," in captured["ass"]
    with pytest.raises(ValueError, match="caption band"):
        short.render(video, [(10.0, 16.0)], tmp_path / "s2.mp4", caption_band=900, **_kw(bg, mascot, font))


def test_sibling_speech_wav_replaces_source_audio_unless_disabled(fake_media, tmp_path, monkeypatch):
    video, bg, mascot, font, clip_plus_outro = fake_media
    stems = video.with_suffix(""); stems.mkdir()
    (stems / "speech.wav").write_bytes(b"w")
    (stems / "no_music.wav").write_bytes(b"n")   # preferred over speech.wav
    captured = {}
    def fake_run(cmd, cwd, **kw):
        captured["cmd"] = cmd
        (Path(cwd) / "rendered.mp4").write_bytes(b"out")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(short.subprocess, "run", fake_run)
    clip_plus_outro[0] = 5.0 + 4.0
    short.render(video, [(10.0, 15.0)], tmp_path / "s.mp4", **_kw(bg, mascot, font))
    cmd = captured["cmd"]
    i = cmd.index(str((stems / "no_music.wav").resolve()))
    assert cmd[i - 1] == "-i" and cmd[i - 5:i - 1] == ["-ss", "10.000", "-t", "5.000"]
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "[1:a]asplit=1" in graph and "[0:a]" not in graph
    short.render(video, [(10.0, 15.0)], tmp_path / "s2.mp4", auto_audio=False, **_kw(bg, mascot, font))
    cmd = captured["cmd"]
    assert str((stems / "no_music.wav").resolve()) not in cmd and "[0:a]asplit=1" in cmd[cmd.index("-filter_complex") + 1]


def test_sibling_music_bed_is_ducked_under_voice_and_credits_copied(fake_media, tmp_path, monkeypatch):
    video, bg, mascot, font, clip_plus_outro = fake_media
    bed = video.with_name(video.stem + ".music_bed.wav"); bed.write_bytes(b"b")
    video.with_name(video.stem + ".music_credits.txt").write_text("Track by X (CC BY 3.0)\n", encoding="utf-8")
    captured = {}
    def fake_run(cmd, cwd, **kw):
        captured["cmd"] = cmd
        (Path(cwd) / "rendered.mp4").write_bytes(b"out")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(short.subprocess, "run", fake_run)
    clip_plus_outro[0] = (2.0 + 1.5) + 4.0
    out = tmp_path / "s.mp4"
    short.render(video, [(10.0, 12.0), (20.0, 21.5)], out, **_kw(bg, mascot, font))
    cmd = captured["cmd"]
    i = cmd.index(str(bed.resolve()))
    assert cmd[i - 5:i - 1] == ["-ss", "10.000", "-t", "11.500"]
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "[1:a]aresample=48000,aformat=channel_layouts=stereo,asplit=2[b0][b1]" in graph
    assert "[tb0][tb1]concat=n=2:v=0:a=1,afade=t=in:d=1.0[clipbed]" in graph
    assert f"volume={short._MUSIC_BED_VOLUME}[bed_scaled]" in graph and "sidechaincompress=" in graph
    assert "amix=inputs=2:duration=first:dropout_transition=0:normalize=0[clipa]" in graph
    assert (tmp_path / "s_music_credits.txt").read_text(encoding="utf-8").startswith("Track by X")
    clip_plus_outro[0] = 2.0 + 4.0
    short.render(video, [(10.0, 12.0)], tmp_path / "s2.mp4", auto_bed=False, **_kw(bg, mascot, font))
    assert str(bed.resolve()) not in captured["cmd"] and "[clipa0]anull[clipa]" in captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
