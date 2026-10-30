"""Pixel checks on real LeoCAD renders (skipped without LeoCAD and an LDraw library)."""
import numpy as np
import pytest
from PIL import Image

from ldraw_xray import Scene

pytestmark = [pytest.mark.leocad, pytest.mark.library]


def pixels(path):
    return np.asarray(Image.open(path).convert('RGBA')).astype(int)


def near(a, rgb, tol=40):
    return int(((abs(a[..., 0] - rgb[0]) < tol) & (abs(a[..., 1] - rgb[1]) < tol) & (abs(a[..., 2] - rgb[2]) < tol)
                & (a[..., 3] > 200)).sum())


def test_highlight_map_axis_backdrop(session, model, tmp_path):
    scene = Scene(model, 'wing.ldr')
    [hl] = session.render(scene, ['highlight:sel=step:3'], ['home'], tmp_path, name='hl')
    raw = pixels(hl['raw'])
    assert near(raw, (255, 0, 255), 60) > 20                              # magenta edges
    flat = pixels(hl['image'])
    assert tuple(flat[2, 2, :3]) == (0xEE, 0xF1, 0xF4)                    # flattened backdrop
    [m] = session.render(scene, ['stud_map'], ['home'], tmp_path, name='map')
    assert near(pixels(m['raw']), (0xED, 0xD4, 0xF7), 25) > 100           # lilac 'up'
    [ax] = session.render(scene, ['axis:point=0,-12,0;direction=1,0,0;length=160;radius=3'], ['front'], tmp_path, name='ax')
    assert near(pixels(ax['raw']), (0x39, 0xFF, 0x14), 70) > 100          # neon rod


def test_xray_makes_parts_translucent(session, model, tmp_path):
    scene = Scene(model, 'wing.ldr')
    [solid] = session.render(scene, [], ['home'], tmp_path, name='solid')
    [xr] = session.render(scene, ['xray:sel=all'], ['home'], tmp_path, name='xr')
    partial = lambda p: int(((pixels(p)[..., 3] > 0) & (pixels(p)[..., 3] < 250)).sum())
    assert partial(xr['raw']) > partial(solid['raw']) * 3


def test_steps_and_cutaway(session, model, tmp_path):
    scene = Scene(model, 'wing.ldr')
    shots = session.render(scene, ['steps'], ['home'], tmp_path, name='steps')
    assert [s['step'] for s in shots] == [1, 3, 4]                       # source numbering, empty step skipped
    [cut] = session.render(Scene(model, 'root.ldr'), ['cutaway:view=front;depth=0.5'], ['front'], tmp_path, name='cut')
    assert cut['camera']['zplanes'][0] > 1


@pytest.mark.shadow
def test_connection_overlays(shadow_config, model, tmp_path):
    from ldraw_xray import Session
    from ldraw_xray import connections
    s = Session(shadow_config)
    report = connections.report(s.parts, model, 'wing.ldr')
    assert report['contacts'] >= 1 and report['groups'][0]['size'] >= 2
    [r] = s.render(Scene(model, 'wing.ldr'), ['components', 'contacts'], ['home'], tmp_path, name='conn')
    assert {l['layer'] for l in r['layers']} == {'components', 'contacts'}
