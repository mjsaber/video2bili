"""Media segment boundaries and YouTube chapter boundaries are independent."""
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from video2yt import merge, merge_cli


def probe_result(duration):
    return SimpleNamespace(stdout=json.dumps({
        'streams': [
            {'codec_type': 'video', 'codec_name': 'h264', 'width': 1920,
             'height': 1080, 'r_frame_rate': '30/1'},
            {'codec_type': 'audio', 'codec_name': 'aac'},
        ], 'format': {'duration': str(duration)},
    }))


@pytest.mark.parametrize('duration', [0, -1, float('nan'), float('inf')])
def test_nonpositive_or_nonfinite_media_duration_rejected(tmp_path, monkeypatch, duration):
    source = tmp_path / 'source.mp4'
    source.touch()
    monkeypatch.setattr(merge.subprocess, 'run', lambda *a, **kw: probe_result(duration))
    with pytest.raises(ValueError, match='positive finite'):
        merge.validate_segments_strict([merge.Segment(source, 'source')])


def test_empty_media_list_rejected():
    with pytest.raises(ValueError, match='at least 1 segment'):
        merge.validate_segments_strict([])


@pytest.mark.parametrize('durations', [[5, 30], [30], [5, 30, 30]])
def test_cli_accepts_short_hook_and_one_or_two_source_segments(tmp_path, monkeypatch, durations):
    monkeypatch.setattr(merge_cli, 'preflight', lambda: None)
    monkeypatch.setattr(merge, 'validate_segments_strict',
                        lambda segments: [setattr(s, 'duration', d) for s, d in zip(segments, durations)])
    commands = []
    monkeypatch.setattr(merge.subprocess, 'run', lambda cmd, **kw: commands.append(cmd))
    monkeypatch.setattr(merge_cli.validate, 'probe', lambda p: SimpleNamespace(
        duration=sum(durations), has_video=True, vcodec='h264', width=1920, height=1080))
    argv = ['--title', 'single source', '-o', str(tmp_path / 'out.mp4')]
    for i in range(len(durations)):
        argv.extend(['--segment', str(tmp_path / f'{i}.mp4'), '--label', str(i)])
    assert merge_cli.run(merge_cli.parse_args(argv)) == tmp_path / 'out.mp4'
    cmd = commands[0]
    assert cmd[cmd.index('-map_chapters') + 1] == '-1'
    assert not (tmp_path / 'out_chapters.txt').exists()


@pytest.mark.parametrize('disabled', [False, True])
def test_omitted_chapters_remove_stale_sidecars(tmp_path, monkeypatch, disabled):
    for suffix in ('chapters', 'ffmeta'):
        (tmp_path / f'out_{suffix}.txt').write_text('old chapters')
    monkeypatch.setattr(merge.subprocess, 'run', lambda *a, **kw: None)
    segments = [merge.Segment(Path('a.mp4'), 'A', 30)] * (3 if disabled else 1)
    merge.render(merge.MergeInputs(segments, 'T', no_chapters=disabled), tmp_path / 'out.mp4')
    assert not (tmp_path / 'out_chapters.txt').exists()
    assert not (tmp_path / 'out_ffmeta.txt').exists()


def test_explicit_chapters_inside_media_segments_use_identical_embedded_and_text_times(tmp_path, monkeypatch):
    chapter_file = tmp_path / 'chapters.txt'
    chapter_file.write_text('0:00 Hook\n0:12 Decision\n0:25 Result\n')
    monkeypatch.setattr(merge_cli, 'preflight', lambda: None)
    monkeypatch.setattr(merge, 'validate_segments_strict',
                        lambda ss: [setattr(s, 'duration', d) for s, d in zip(ss, [5, 35])])
    monkeypatch.setattr(merge.subprocess, 'run', lambda *a, **kw: None)
    monkeypatch.setattr(merge_cli.validate, 'probe', lambda p: SimpleNamespace(
        duration=40, has_video=True, vcodec='h264', width=1920, height=1080))
    args = merge_cli.parse_args([
        '--segment', 'hook.mp4', '--label', 'Hook', '--segment', 'battle.mp4', '--label', 'Battle',
        '--title', 'T', '-o', str(tmp_path / 'out.mp4'), '--chapters-file', str(chapter_file),
    ])
    merge_cli.run(args)
    assert (tmp_path / 'out_chapters.txt').read_text() == '00:00 Hook\n00:12 Decision\n00:25 Result\n'
    metadata = (tmp_path / 'out_ffmeta.txt').read_text()
    for start, end in [(0, 12000), (12000, 25000), (25000, 40000)]:
        assert f'START={start}\nEND={end}\n' in metadata


@pytest.mark.parametrize('text', [
    '', '00:00 A\n00:10 B', '00:01 A\n00:12 B\n00:24 C',
    '00:00 A\n00:20 B\n00:10 C', '00:00 A\n00:10 B\n00:10 C',
    '00:00 A\n00:09 B\n00:20 C', '00:00 A\n00:10 B\n00:31 C',
    '00:00 A\n00:10 B\n00:40 C', '00:00 A\n00:10 B\n00:50 C',
    '00:00 A\n00:10 B\n00:60 C', '00:00 A\n00:10 B\n00:20',
    '00:00 A\n00:10 B\n01:60:00 C', '0 A\n10 B\n20 C',
])
def test_invalid_explicit_chapters_fail(text):
    with pytest.raises(ValueError, match='chapter'):
        merge.parse_chapters_text(text, total_duration=40)


def test_hours_and_multilingual_labels():
    chapters = merge.parse_chapters_text('00:00 開場\n00:10 戰鬥\n01:00:00 結局', total_duration=3610)
    assert [(c.start_seconds, c.label) for c in chapters] == [(0, '開場'), (10, '戰鬥'), (3600, '結局')]


def test_auto_chapters_quantize_boundaries_for_identical_text_and_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(merge.subprocess, 'run', lambda *a, **kw: None)
    segments = [merge.Segment(Path('a.mp4'), 'A', 10.6),
                merge.Segment(Path('b.mp4'), 'B', 10.6),
                merge.Segment(Path('c.mp4'), 'C', 12)]
    merge.render(merge.MergeInputs(segments, 'T'), tmp_path / 'out.mp4')
    assert (tmp_path / 'out_chapters.txt').read_text() == '00:00 A\n00:10 B\n00:21 C\n'
    metadata = (tmp_path / 'out_ffmeta.txt').read_text()
    assert 'START=10000\nEND=21000' in metadata


def test_chapter_options_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        merge_cli.parse_args(['--title', 'T', '--chapters-file', 'c.txt', '--no-chapters'])


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg unavailable')
def test_real_ffmpeg_short_single_segment(tmp_path):
    source = tmp_path / 'source.mp4'
    subprocess.run([
        'ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=1920x1080:r=30',
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '0.5',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source),
    ], check=True, capture_output=True)
    output = tmp_path / 'merged.mp4'
    assert merge_cli.run(merge_cli.parse_args([
        '--segment', str(source), '--label', 'Hook', '--title', 'Smoke', '-o', str(output),
    ])) == output
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_chapters', '-of', 'json', str(output)],
                            check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)['chapters'] == []


def test_explicit_labels_escape_ffmetadata_syntax_only(tmp_path, monkeypatch):
    monkeypatch.setattr(merge.subprocess, 'run', lambda *a, **kw: None)
    text = '00:00 A=B;#C\\D\n00:10 戰鬥\n00:20 結局\n'
    chapters = merge.parse_chapters_text(text, total_duration=30)
    merge.render(merge.MergeInputs([merge.Segment(Path('source.mp4'), 'source', 30)],
                                   'T', chapters=chapters), tmp_path / 'out.mp4')
    assert (tmp_path / 'out_chapters.txt').read_text() == text
    assert 'title=A\\=B\\;\\#C\\\\D\n' in (tmp_path / 'out_ffmeta.txt').read_text()


def test_invalid_explicit_chapters_fail_before_render_or_sidecar_changes(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(merge.subprocess, 'run', lambda *a, **kw: commands.append(a))
    old = tmp_path / 'out_chapters.txt'
    old.write_text('old successful render')
    inputs = merge.MergeInputs([merge.Segment(Path('source.mp4'), 'source', 30)],
                               'T', chapters=[merge.Chapter(0, 'Only one')])
    with pytest.raises(ValueError, match='at least 3 chapters'):
        merge.render(inputs, tmp_path / 'out.mp4')
    assert commands == []
    assert old.read_text() == 'old successful render'


@pytest.mark.parametrize('start', [-1, 0.5, float('nan'), float('inf'), True])
def test_programmatic_chapters_reject_noninteger_timestamps(start):
    chapters = [merge.Chapter(0, 'A'), merge.Chapter(start, 'B'), merge.Chapter(20, 'C')]
    with pytest.raises(ValueError, match='whole seconds'):
        merge.validate_chapters(chapters, 40)
