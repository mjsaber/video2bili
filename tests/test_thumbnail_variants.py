"""Local packaging variants, measured text fitting, and reproducible manifests."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'thumbnail_polish.py'
spec = importlib.util.spec_from_file_location('thumbnail_polish_variants', SCRIPT)
polish = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = polish
spec.loader.exec_module(polish)


@pytest.fixture(autouse=True)
def available_font(monkeypatch):
    if not Path(polish.FONT_PATH).exists():
        # Keep the compositor tests portable without requiring macOS fonts.
        font = polish.ImageFont.truetype('DejaVuSans.ttf', 20)
        monkeypatch.setattr(polish, 'FONT_PATH', font.path)
        monkeypatch.setattr(polish, 'FONT_INDEX', 0)


@pytest.mark.parametrize('text', ['21億屬性直接清場', '1234567890', 'WWWW1111', '一回合翻倍100%'])
def test_rows_fit_actual_glyph_bounds_including_strokes(text):
    row = polish.fit_title_row(text, 180, 500, 16, -10)
    assert row.bbox[2] - row.bbox[0] <= 500
    assert row.font.size <= 180
    canvas = Image.new('RGBA', (polish.W, polish.H))
    polish.render_title_row(canvas, text, 180, 20, 40, (255, 255, 255, 255),
                            (0, 0, 0, 255), 16, -10, (0, 0), 0, 0, max_width=500)
    ink = canvas.getbbox()
    assert ink is not None
    assert 20 <= ink[0] < ink[2] <= 520
    assert ink[1] >= 40


def test_digit_rows_use_actual_glyph_widths():
    digits = polish.fit_title_row('1111', 180, 700, 16, -10)
    wide = polish.fit_title_row('WWWW', 180, 700, 16, -10)
    assert digits.bbox[2] - digits.bbox[0] < wide.bbox[2] - wide.bbox[0]


@pytest.mark.parametrize('text', ['', '  ', 'hello\nworld', 'A' * 1000])
def test_invalid_or_unreadably_long_rows_are_rejected(text):
    with pytest.raises(ValueError):
        polish.fit_title_row(text, 180, 600, 16, -10)


@pytest.fixture
def assets(tmp_path):
    paths = {}
    for name, size, color in [('bg', (1280, 720), (60, 50, 40, 255)),
                              ('card', (220, 320), (190, 140, 40, 255)),
                              ('card2', (220, 320), (40, 120, 190, 255)),
                              ('logo', (80, 40), (255, 255, 255, 255)),
                              ('mascot', (150, 250), (190, 60, 50, 255))]:
        paths[name] = tmp_path / f'{name}.png'
        Image.new('RGBA', size, color).save(paths[name])
    return paths


def argv_for(assets, output):
    return ['--bg', str(assets['bg']), '--card', str(assets['card']),
            '--logo', str(assets['logo']), '--mascot', str(assets['mascot']),
            '--primary', '鉤牙海盜', '--secondary', '21億屬性翻倍', '--output', str(output)]


def test_payoff_layout_promotes_secondary_and_preserves_tertiary_and_card2(assets, monkeypatch):
    rows = []
    real_render = polish.render_title_row
    def record(canvas, text, font_size, *args, **kwargs):
        rows.append((text, font_size))
        return real_render(canvas, text, font_size, *args, **kwargs)
    monkeypatch.setattr(polish, 'render_title_row', record)
    result = polish.build(assets['bg'], assets['card'], None, None, '鉤牙海盜',
                          '21億屬性', '零敗收場', card2_path=assets['card2'], layout='payoff')
    assert result.size == (1280, 720)
    assert rows[0][0] == '21億屬性'
    assert rows[0][1] > rows[1][1]
    assert [row[0] for row in rows] == ['21億屬性', '鉤牙海盜', '零敗收場']


def test_brand_remains_default(assets, monkeypatch):
    rows = []
    monkeypatch.setattr(polish, 'render_title_row', lambda canvas, text, *a, **kw: rows.append(text))
    polish.build(assets['bg'], assets['card'], assets['logo'], None, '鉤牙海盜', '百萬屬性')
    assert rows == ['鉤牙海盜', '百萬屬性']


@pytest.mark.parametrize('visible', ['front', 'back'])
@pytest.mark.parametrize('sizes', [((220, 320), (220, 320)), ((480, 280), (120, 360))])
def test_card_fan_preserves_each_rotated_card_without_clipping(tmp_path, visible, sizes):
    paths = [tmp_path / 'back.png', tmp_path / 'front.png']
    for name, path, size in zip(['back', 'front'], paths, sizes):
        Image.new('RGBA', size, (255, 0, 0, 255) if name == visible else (0, 0, 0, 0)).save(path)
    index = 0 if visible == 'back' else 1
    tilt = polish.FAN_BACK_TILT if visible == 'back' else polish.FAN_FRONT_TILT
    with Image.open(paths[index]) as source:
        rotated = source.rotate(tilt, expand=True, resample=Image.BICUBIC)
    expected = rotated.crop(rotated.getbbox())
    actual = polish.combine_cards_fan(*paths)
    assert actual.size == expected.size
    assert actual.tobytes() == expected.tobytes()


def test_variant_manifest_records_assets_title_hypothesis_and_pending_status(assets, tmp_path):
    output = tmp_path / 'variant-a.png'
    assert polish.main(argv_for(assets, output) + [
        '--layout', 'payoff', '--no-logo', '--no-mascot', '--card2', str(assets['card2']),
        '--tertiary', '零敗收場', '--variant-id', 'payoff-a', '--video-title', 'Test title',
        '--hypothesis', 'A visible numerical result improves clicks.',
    ]) == 0
    manifest = json.loads(output.with_suffix('.variant.json').read_text())
    assert manifest['id'] == 'payoff-a'
    assert manifest['title'] == 'Test title'
    assert manifest['hypothesis'] == 'A visible numerical result improves clicks.'
    assert manifest['layout'] == 'payoff'
    assert manifest['style'] == 'anime-sketch'
    assert manifest['texts'] == {'primary': '鉤牙海盜', 'secondary': '21億屬性翻倍', 'tertiary': '零敗收場'}
    assert manifest['status'] == 'pending_manual_studio_experiment'
    assert manifest['created_at'].endswith('+00:00')
    assert manifest['thumbnail_path'] == str(output.resolve())
    assert manifest['thumbnail_sha256'] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert manifest['assets']['card2']['path'] == str(assets['card2'].resolve())
    assert manifest['assets']['card']['sha256'] == hashlib.sha256(assets['card'].read_bytes()).hexdigest()
    assert manifest['assets']['logo'] is None
    assert manifest['assets']['mascot'] is None
    with Image.open(tmp_path / 'variant-a_mobile.png') as image:
        assert image.size == (320, 180)


@pytest.mark.parametrize('options', [
    ['--variant-id', 'v1'], ['--video-title', 'Title'], ['--hypothesis', 'Theory'],
    ['--variant-id', 'v1', '--video-title', 'Title', '--hypothesis', '  '],
])
def test_partial_variant_metadata_fails_before_output(assets, tmp_path, options):
    output = tmp_path / 'not-created.png'
    with pytest.raises(ValueError):
        polish.main(argv_for(assets, output) + options)
    assert not output.exists()


def test_variant_refuses_overwrite(assets, tmp_path):
    output = tmp_path / 'existing.png'
    output.write_bytes(b'existing user artifact')
    with pytest.raises(FileExistsError):
        polish.main(argv_for(assets, output) + [
            '--variant-id', 'v1', '--video-title', 'Title', '--hypothesis', 'Theory'])
    assert output.read_bytes() == b'existing user artifact'


def test_sketch_default_preserves_pale_paper_and_dark_title(assets):
    Image.new('RGB', (1280, 720), (252, 250, 245)).save(assets['bg'])
    result = polish.build(assets['bg'], assets['card'], None, None, 'TEST', 'RESULT')
    # Empty left margin remains paper, with no dark scrim or gold tint.
    assert min(result.getpixel((5, 100))) >= 240
    # Title itself must have dark ink on that pale ground.
    ink = result.crop((20, 140, 600, 280)).convert('L')
    assert ink.getextrema()[0] < 60


def test_sketch_title_scrim_retains_visible_pastel_background(assets):
    Image.new('RGB', (1280, 720), (185, 220, 203)).save(assets['bg'])
    result = polish.build(assets['bg'], assets['card'], None, None, 'TEST', 'RESULT')
    red, green, blue = result.getpixel((5, 100))[:3]
    assert green - red >= 12
    assert green > blue > red
    assert min(red, green, blue) >= 200


def test_legacy_thumbnail_style_is_available(assets):
    Image.new('RGB', (1280, 720), (252, 250, 245)).save(assets['bg'])
    result = polish.build(assets['bg'], assets['card'], None, None, 'TEST', 'RESULT',
                          style='warm-tavern')
    assert max(result.getpixel((5, 100))) < 100


def test_unknown_thumbnail_style_is_rejected(assets):
    with pytest.raises(ValueError, match='style'):
        polish.build(assets['bg'], assets['card'], None, None, 'TEST', 'RESULT',
                     style='unknown')
