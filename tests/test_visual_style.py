"""The selected visual style must survive generation and video composition."""
from pathlib import Path

import pytest
from PIL import Image

from video2yt import image_gen_cli, intro_cli, intro_compose, visual_style


@pytest.mark.parametrize('backend', ['codex', 'gemini'])
def test_default_image_style_reaches_both_backends(backend, monkeypatch, tmp_path):
    captured = []
    def generate(prompt, **kwargs):
        captured.append(prompt)
        return Image.new('RGB', (16, 9))
    monkeypatch.setattr(image_gen_cli.image_gen, f'generate_{backend}', generate)
    monkeypatch.setenv('GEMINI_API_KEY', 'test')
    monkeypatch.setattr(image_gen_cli, 'load_dotenv', lambda: None)
    args = image_gen_cli.parse_args(['--prompt', 'A pirate treasure chest',
                                   '--backend', backend, '--fit', 'none',
                                   '-o', str(tmp_path / 'bg.png')])
    image_gen_cli.run(args)
    assert 'A pirate treasure chest' in captured[0]
    assert 'Japanese anime pencil-sketch' in captured[0]
    assert 'graphite' in captured[0]
    assert 'ivory' in captured[0]
    for color in ['mint green', 'powder blue', 'peach pink', 'apricot yellow']:
        assert color in captured[0]
    assert 'clearly visible' in captured[0]
    assert 'Predominantly paper-white and graphite' not in captured[0]


def test_image_none_style_preserves_exact_prompt(monkeypatch, tmp_path):
    captured = []
    def generate(prompt, **kwargs):
        captured.append(prompt)
        return Image.new('RGB', (16, 9))
    monkeypatch.setattr(image_gen_cli.image_gen, 'generate_codex', generate)
    args = image_gen_cli.parse_args(['--prompt', 'Original custom art direction',
                                   '--style', 'none', '--fit', 'none',
                                   '-o', str(tmp_path / 'custom.png')])
    image_gen_cli.run(args)
    assert captured == ['Original custom art direction']


def test_intro_defaults_to_sketch_mascot_and_theme(tmp_path, monkeypatch):
    mascot = tmp_path / 'mascot.png'
    image = Image.new('RGBA', (10, 10))
    image.putpixel((5, 5), (40, 44, 49, 255))
    image.save(mascot)
    monkeypatch.setattr(visual_style, 'SKETCH_MASCOT', mascot)
    args = intro_cli.parse_args(['--audio', 'a.wav', '--bg', 'b.png', '--srt', 'a.srt',
                                '--cards', 'cards.txt', '-o', 'intro.mp4'])
    assert args.style == 'anime-sketch'
    assert args.mascot == mascot


def test_intro_legacy_selects_legacy_mascot():
    args = intro_cli.parse_args(['--audio', 'a.wav', '--bg', 'b.png', '--srt', 'a.srt',
                                '--cards', 'cards.txt', '-o', 'intro.mp4',
                                '--style', 'warm-tavern'])
    assert args.mascot == Path('assets/cta/src/mascot_raw.png')


def test_sketch_intro_preserves_paper_and_uses_dark_readable_text():
    graph = intro_compose._build_filter([], 2, '/F.ttc', show_title=True,
                                        style='anime-sketch')
    assert 'eq=brightness' not in graph
    assert 'fontcolor=0x282C31' in graph
    assert 'PrimaryColour=&H00312C28' in graph
    assert 'OutlineColour=&H00F5FAFC' in graph
    assert 'Shadow=0' in graph


def test_legacy_intro_still_dims_background():
    graph = intro_compose._build_filter([], 2, '/F.ttc', style='warm-tavern')
    assert 'eq=brightness=-0.04' in graph
    assert 'force_style' not in graph


@pytest.mark.parametrize('mode', ['RGB', 'RGBA'])
def test_opaque_generated_mascot_cannot_become_default(tmp_path, monkeypatch, mode):
    mascot = tmp_path / 'opaque.png'
    Image.new(mode, (10, 10), 'white').save(mascot)
    monkeypatch.setattr(visual_style, 'SKETCH_MASCOT', mascot)
    assert visual_style.default_mascot('anime-sketch') == visual_style.LEGACY_MASCOT


def test_missing_sketch_mascot_uses_existing_transparent_asset(tmp_path, monkeypatch):
    monkeypatch.setattr(visual_style, 'SKETCH_MASCOT', tmp_path / 'missing.png')
    assert visual_style.default_mascot('anime-sketch') == visual_style.LEGACY_MASCOT


def test_shipped_sketch_mascot_has_transparent_surroundings_and_opaque_character(monkeypatch):
    mascot = Path(__file__).resolve().parents[1] / 'assets/branding/anime_sketch/mascot.png'
    assert mascot.is_file()
    with Image.open(mascot) as image:
        assert image.mode == 'RGBA'
        alpha = image.getchannel('A')
        assert alpha.getextrema() == (0, 255)
        for box in [(0, 0, image.width, 50), (0, image.height - 50, image.width, image.height)]:
            assert alpha.crop(box).getextrema() == (0, 0)
        # Preserve light character details while clearing enclosed hair loops.
        for point in [(490, 560), (450, 900), (410, 330)]:
            assert alpha.getpixel(point) == 255
        for point in [(224, 609), (116, 541), (816, 651), (949, 596)]:
            assert alpha.getpixel(point) == 0
    monkeypatch.setattr(visual_style, 'SKETCH_MASCOT', mascot)
    assert visual_style.default_mascot('anime-sketch') == mascot
