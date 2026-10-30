"""Pixel and artifact checks on real LeoCAD renders."""
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

pytestmark = [pytest.mark.leocad, pytest.mark.library]


def pixels(path):
    with Image.open(path) as image:
        return np.asarray(image.convert('RGBA')).astype(int)


def near(array, rgb, tolerance=40):
    close = (abs(array[..., :3] - rgb) < tolerance).all(axis=2)
    return int((close & (array[..., 3] > 200)).sum())


def render(session, model, directory, layers, *, section='wing.ldr', view='home'):
    manifest = session.render(model, section=section, output=directory, layers=layers,
                              views=[view], keep_intermediates=True)
    return [{**panel, 'raw': directory / panel['raw'], 'image': directory / panel['image']}
            for panel in manifest['panels']]


def test_highlight_map_axis_backdrop(session, model, tmp_path):
    [highlight] = render(session, model, tmp_path / 'highlight', [dict(layer='highlight', select='step:3')])
    assert near(pixels(highlight['raw']), (255, 0, 255), 60) > 20
    assert tuple(pixels(highlight['image'])[2, 2, :3]) == (0xEE, 0xF1, 0xF4)
    [studs] = render(session, model, tmp_path / 'map', [dict(layer='stud_map')])
    assert near(pixels(studs['raw']), (0xED, 0xD4, 0xF7), 25) > 100
    [axis] = render(session, model, tmp_path / 'axis',
                    [dict(layer='axis', point=[0, -12, 0], direction=[1, 0, 0], length=160, radius=3)], view='front')
    assert near(pixels(axis['raw']), (0x39, 0xFF, 0x14), 70) > 100


def test_xray_makes_parts_translucent(session, model, tmp_path):
    [solid] = render(session, model, tmp_path / 'solid', [])
    [xray] = render(session, model, tmp_path / 'xray', [dict(layer='xray', select='all')])

    def partial(path):
        alpha = pixels(path)[..., 3]
        return int(((alpha > 0) & (alpha < 250)).sum())

    assert partial(xray['raw']) > partial(solid['raw']) * 3


def test_steps_and_cutaway(session, model, tmp_path):
    shots = render(session, model, tmp_path / 'steps', [dict(layer='steps')])
    assert [shot['step'] for shot in shots] == [1, 3, 4]
    shots = render(session, model, tmp_path / 'sparse', [dict(layer='steps', numbers=[1, 4])])
    assert [shot['step'] for shot in shots] == [1, 4]
    [cut] = render(session, model, tmp_path / 'cut', [dict(layer='cutaway', view='front', depth=0.5)],
                   section='root.ldr', view='front')
    assert cut['camera']['zplanes'][0] > 1


@pytest.mark.shadow
def test_connection_overlays(shadow_config, model, tmp_path):
    from ldraw_xray import Session, connections
    session = Session(shadow_config)
    report = connections.report(session.parts, model, 'wing.ldr')
    assert report['contacts'] >= 1 and report['groups'][0]['size'] >= 2
    [result] = render(session, model, tmp_path / 'connections', [dict(layer='components'), dict(layer='contacts')])
    assert {layer['layer'] for layer in result['layers']} == {'components', 'contacts'}


def test_overlays_without_shadow_metadata(session, model, tmp_path):
    from ldraw_xray import Session
    session = Session(replace(session.config, shadows=()))
    layers = [dict(layer='components'), dict(layer='xray', select='all'),
              dict(layer='contacts'), dict(layer='collisions')]
    [result] = render(session, model, tmp_path / 'overlays', layers)
    assert [layer['layer'] for layer in result['layers']] == [layer['layer'] for layer in layers]
    assert result['coverage'] > 0 and result['image'].is_file()


def test_real_cli_json_and_replay(session, model, tmp_path):
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, 'PYTHONPATH': str(root)}
    command = [sys.executable, '-m', 'ldraw_xray', '--cache-dir', str(session.config.cache_dir)]
    first = subprocess.run([*command, 'render', str(model), '--section', 'wing.ldr',
                            '--stud-map', '-o', str(tmp_path / 'cli')],
                           env=environment, capture_output=True, text=True, timeout=120)
    assert first.returncode == 0, first.stderr
    result = json.loads(first.stdout)
    assert Path(result['images'][0]['image']).is_file()
    replay = subprocess.run([*command, 'board', 'run', result['recipe'], '-o', str(tmp_path / 'replay')],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=120)
    assert replay.returncode == 0, replay.stderr
    replay_result = json.loads(replay.stdout)
    assert pixels(result['images'][0]['image']).shape == pixels(replay_result['images'][0]['image']).shape
    assert np.array_equal(pixels(result['images'][0]['image']), pixels(replay_result['images'][0]['image']))
    assert not (tmp_path / 'replay' / 'mosaic.png').exists()
