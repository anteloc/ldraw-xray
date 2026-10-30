import numpy as np
import pytest

from ldraw_xray.mpd import Document, Placement, emit, step_map
from ldraw_xray.select import select


def test_blocks_lines_and_steps(model):
    doc = Document.read(model)
    assert doc.order == ['root.ldr', 'wing.ldr', 'marker.dat']
    wing = doc.block('WING.LDR')
    ps = wing.placements()
    assert [p.line for p in ps] == [14, 17, 19]
    assert [p.step for p in ps] == [1, 3, 4]          # an empty source step is counted
    assert wing.step_count() == 4 and wing.empty_leading_steps() == 0
    assert doc.block('marker.dat').is_part
    assert list(doc.parents_of('wing.ldr')) == ['root.ldr']


def test_description_starting_with_step_is_not_a_step(tmp_path):
    path = tmp_path / 'steps.ldr'
    path.write_text('0 Steps 70 to 90\n0 Name: steps.ldr\n1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n'
                    '0 STEP\n0 ROTSTEP 35 55 0 ABS\n1 4 0 -24 0 1 0 0 0 1 0 0 0 1 3001.dat\n')
    block = Document.read(path).root
    assert [p.step for p in block.placements()] == [1, 3]
    assert block.header() == ['0 Steps 70 to 90', '0 Name: steps.ldr']


def test_single_ldr(tmp_path):
    path = tmp_path / 'plain.ldr'
    path.write_text('0 Plain\n1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n')
    doc = Document.read(path)
    assert not doc.multipart and doc.root.name == 'plain.ldr'
    assert doc.text() == path.read_text()


def test_flatten_transforms_and_inherits_colour(model):
    doc = Document.read(model)
    turned = doc.block('root.ldr').placements()[2]           # colour 1, rotated 90 degrees about Y
    leaves = list(doc.flatten(turned))
    assert [l.colour for l in leaves] == ['1', '14', '2']     # 16 inherits the placing colour
    assert np.allclose(leaves[1].pos, [100, -32, -20])        # (20,-8,0) turned about Y, then moved
    assert leaves[1].origin == (7, 17)
    assert list(doc.flatten(doc.block('root.ldr').placements()[3]))[0].ref == 'marker.dat'  # embedded parts are leaves


def test_placement_text_round_trip():
    p = Placement.parse('1 4 10 -24.5 0 0 0 1 0 1 0 -1 0 0 3001.dat', 9)
    assert Placement.parse(p.text()).text() == p.text()
    assert p.text() == '1 4 10 -24.5 0 0 0 1 0 1 0 -1 0 0 3001.dat'


def test_emit_final_step_and_dense_steps(model):
    ps = Document.read(model).block('wing.ldr').placements()
    assert step_map(ps) == {1: 1, 3: 2, 4: 3}
    lines = emit(['0 head'], ps, keep_steps=True)
    assert lines.count('0 STEP') == 3                         # no empty step written
    finals = [p.moved(final=True) for p in ps]
    assert emit([], finals, keep_steps=False)[0].startswith('1 ')   # all-final: no leading empty step
    mixed = [ps[0], ps[1].moved(final=True)]
    assert emit([], mixed, keep_steps=False) == [ps[0].text(), '0 STEP', ps[1].text(), '0 STEP']
    with pytest.raises(ValueError):
        emit([], mixed, keep_steps=True)


def test_selection_terms(model):
    doc = Document.read(model)
    root = doc.block('root.ldr').placements()
    wing = doc.block('wing.ldr').placements()
    assert select('all', wing) == {0, 1, 2}
    assert select('step:3-4', wing) == {1, 2}
    assert select('part:302?', wing) == {1, 2}
    assert select('part:3022.dat|colour:16', wing) == {0, 1}
    assert select('!colour:2', wing) == {0, 1}
    assert select('line:14,19', wing) == {0, 2}
    assert select('section', root, section='wing.ldr') == {1, 2}
    assert select('ref:marker.dat', root) == {3}
    with pytest.raises(ValueError):
        select('bogus:1', wing)
