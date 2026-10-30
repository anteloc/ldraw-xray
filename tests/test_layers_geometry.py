import numpy as np
import pytest

from ldraw_xray import camera as cam
from ldraw_xray.geometry import Bounds, basis_y, map_axis, rotation, stud_bucket
from ldraw_xray.layers import Build, Scene, apply, parse_layer
from ldraw_xray.mpd import Block


def plan(model, layers, context='isolate', section='wing.ldr'):
    return apply(Build(Scene(model, section, context)), layers).plan()


def rendered_lines(p):
    return Block(p.submodel, p.doc.block(p.submodel).lines).lines


def test_stud_buckets_and_rotation():
    assert stud_bucket(np.eye(3)) == 'up'
    assert stud_bucket(np.diag([1, -1, -1])) == 'down'
    assert stud_bucket(rotation((0, 0, 1), 90)) == '+x'
    assert stud_bucket(rotation((1, 0, 0), 90)) == '-z'
    assert stud_bucket(rotation((0, 0, 1), 30)) == 'angled'
    assert np.allclose(basis_y((1, 0, 0)) @ [0, 1, 0], [1, 0, 0])


def test_axis_maps_like_the_75060_cockpit():
    # Section axis (0,-18,0) along +Z; section placed at (0,-164,-300) with matrix 0 0 -1 / 0 1 0 / 1 0 0.
    point, direction = map_axis((0, -18, 0), (0, 0, 1), (0, -164, -300), [[0, 0, -1], [0, 1, 0], [1, 0, 0]])
    assert np.allclose(point, [0, -182, -300]) and np.allclose(direction, [-1, 0, 0])


def test_highlight_moves_selection_to_final_step(model):
    p = plan(model, ['highlight:sel=step:3'])
    assert p.final_step == 2 and p.highlight and not p.fade
    lines = rendered_lines(p)
    assert lines.index('0 STEP') < lines.index(next(l for l in lines if l.endswith('3022.dat')))


def test_parent_context_defaults(model):
    p = plan(model, ['highlight', 'ghost'], context='parent')
    assert p.submodel == 'root.ldr' and p.fade and p.final_step == 2
    assert len(p.parent_placements) == 2
    with pytest.raises(ValueError, match='ghost needs a highlight'):
        plan(model, ['ghost'])
    with pytest.raises(ValueError, match='source-step'):
        plan(model, ['steps', 'highlight:sel=all'])


def test_xray_recolours_inside_children(model):
    p = plan(model, ['xray:sel=ref:wing.ldr'], section='root.ldr')
    refs = [l.split()[-1] for l in rendered_lines(p) if l.startswith('1 ')]
    colours = [l.split()[1] for l in rendered_lines(p) if l.startswith('1 ')]
    assert 'wing.ldr' not in refs                     # flattened so explicit colours can change
    assert colours.count('47') == 6


def test_stud_map_counts(model):
    p = plan(model, ['stud_map'])
    record = p.records[0]
    assert record['counts'] == {'up': 2, '+x': 1} or record['counts'] == {'up': 2, '-x': 1}
    assert {e['code'] for e in p.legend} >= {9007}


def test_pose_rotates_about_axis(model):
    p = plan(model, ['pose:sel=step:3;point=20,-8,0;direction=0,1,0;angle=90'])
    line = next(l for l in rendered_lines(p) if l.endswith('3022.dat'))
    assert line.split()[2:5] == ['20', '-8', '0']     # on the axis: position unchanged
    assert line.split()[5:14] == ['0', '0', '1', '0', '1', '0', '-1', '0', '0']


def test_axis_adds_marker_block(model):
    p = plan(model, ['axis:point=0,-12,0;direction=1,0,0;length=100;radius=2'])
    assert 'xray-axis-0.dat' in p.doc.blocks
    assert any(l.startswith('1 9008 ') for l in rendered_lines(p))


def test_parse_layer_errors():
    assert parse_layer('pose:point=1,2,3;angle=45') == dict(layer='pose', point=(1.0, 2.0, 3.0), angle=45.0)
    with pytest.raises(ValueError, match='Unknown layer'):
        parse_layer('glow')
    with pytest.raises(ValueError, match='takes'):
        parse_layer('ghost:sel=all')


def test_fitted_camera_contains_points_and_cutaway_plane():
    b = Bounds([-40, -24, -20], [40, 0, 20])
    c = cam.fitted(b, 'front')
    pos = np.array(c.position)
    tan_v = np.tan(np.radians(15))
    for corner in [[x, y, z] for x in (-40, 40) for y in (-24, 0) for z in (-20, 20)]:
        rel = np.array(corner) - pos
        assert abs(rel[1]) / rel[2] <= tan_v + 1e-9 and abs(rel[0]) / rel[2] <= tan_v * 4 / 3 + 1e-9
    cut = cam.cutaway(b, 'front', 0.5)
    assert abs(cut.zplanes[0] - (0 - cut.position[2])) < 1e-6   # plane z=0 from a camera on -Z
    with pytest.raises(ValueError):
        cam.cutaway(b, 'home')
