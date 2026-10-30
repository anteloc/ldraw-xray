import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from ldraw_xray.config import ConfigError, XrayConfig
from ldraw_xray.mosaic import _lines, compose_mosaic
from ldraw_xray.palette import SWATCHES, check_palette, resolve


def fixture(tmp_path, mode='views', colours=('red', 'blue', 'green', 'yellow')):
    panels = []
    for i, colour in enumerate(colours):
        path = tmp_path / f'{i}.png'
        Image.new('RGB', (400, 300), colour).save(path)
        panels.append(dict(image=path.name, label=f'View {i}', subject='section frame',
                           camera={'position': [0, -400, -400], 'target': [0, 0, 0], 'up': [0, -1, 0], 'fov': 30}))
    manifest = tmp_path / 'panels.json'
    manifest.write_text(json.dumps(dict(mode=mode, panels=panels, legend=['Colours: test'])))
    return manifest


def test_grid_order_provenance_and_inputs_untouched(tmp_path):
    manifest = fixture(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    report = compose_mosaic(manifest, tmp_path / 'board.png', panel_width=400)
    with Image.open(report['output']) as board:
        for panel, colour in zip(report['panels'], [(255, 0, 0), (0, 0, 255), (0, 128, 0), (255, 255, 0)]):
            x, y, w, h = panel['image_box']
            assert board.getpixel((x + w // 2, y + h // 2)) == colour
            assert panel['sha256'] == hashlib.sha256((tmp_path / Path(panel['image']).name).read_bytes()).hexdigest()
    assert all((tmp_path / n).read_bytes() == d for n, d in before.items())
    assert report['duplicates'] == [] and report['legend'] == ['Colours: test']
    assert json.loads((tmp_path / 'board.json').read_text()) == report


def test_analysis_mode_and_overwrite_protection(tmp_path):
    manifest = fixture(tmp_path, 'analysis')
    compose_mosaic(manifest, tmp_path / 'board.png')
    data = json.loads(manifest.read_text())
    data['panels'][1]['camera']['fov'] = 45
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='same camera'):
        compose_mosaic(manifest, tmp_path / 'other.png')
    with pytest.raises(ValueError, match='exists'):
        compose_mosaic(fixture(tmp_path), tmp_path / 'board.png')
    with pytest.raises(ValueError, match='overwrite inputs'):
        compose_mosaic(fixture(tmp_path), tmp_path / '0.png', force=True)


def test_duplicates_flagged(tmp_path):
    report = compose_mosaic(fixture(tmp_path, colours=('red', 'red', 'blue')), tmp_path / 'b.png')
    assert report['duplicates'] == [dict(panels=[1, 2], difference=0.0)]


def test_word_wrap_never_splits_words():
    draw = ImageDraw.Draw(Image.new('RGB', (10, 10)))
    font = ImageFont.load_default(size=20)
    text = 'Source step 11: seven curved-top bricks along one edge make the rounded bilge of the hull'
    lines = _lines(draw, text, 300, font)
    assert ' '.join(lines) == text and len(lines) > 1


def test_config_precedence_and_errors(fake_lib, tmp_path, monkeypatch):
    other = tmp_path / 'other'
    from conftest import fake_library
    fake_library(other)
    monkeypatch.setenv('LDRAW_DIR', str(other))
    monkeypatch.delenv('LDRAW_SHADOW', raising=False)
    assert XrayConfig.resolve(cache_dir=tmp_path).ldraw_lib == other.resolve()
    assert XrayConfig.resolve(fake_lib, cache_dir=tmp_path).ldraw_lib == fake_lib.resolve()
    monkeypatch.delenv('LDRAW_DIR')
    monkeypatch.delenv('LDRAWDIR', raising=False)
    with pytest.raises(ConfigError, match='LDRAW_DIR'):
        XrayConfig.resolve(cache_dir=tmp_path)
    with pytest.raises(ConfigError, match='Not an LDraw library'):
        XrayConfig.resolve(tmp_path, cache_dir=tmp_path)
    with pytest.raises(ConfigError, match='shadow'):
        XrayConfig.resolve(fake_lib, [str(tmp_path / 'missing')], cache_dir=tmp_path)
    shadow = tmp_path / 'shadow' / 'parts'
    shadow.mkdir(parents=True)
    monkeypatch.setenv('LDRAW_SHADOW', str(shadow.parent))
    assert XrayConfig.resolve(fake_lib, cache_dir=tmp_path).shadows == (shadow.parent.resolve(),)
    assert XrayConfig.resolve(fake_lib, cache_dir=tmp_path, no_shadow=True).shadows == ()


def test_palette_resolution_and_check(fake_lib):
    assert resolve('group:B') == 9012 and resolve('Xray_Glass') == 9031 and resolve('47') == 47
    report = check_palette(fake_lib / 'LDConfig.ldr')
    assert report['ok'] and len(report['swatches']) == len(SWATCHES)
    assert len({s.code for s in SWATCHES}) == len(SWATCHES)


@pytest.mark.library
def test_palette_against_installed_ldconfig(library):
    from ldraw_xray.library import _ldconfig
    report = check_palette(_ldconfig(library))
    assert report['ok'], [r for r in report['swatches'] if r['delta_e'] < 16]
