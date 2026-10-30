"""Public-interface behavior, with only LeoCAD and the parts library substituted."""
import json
import re
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from ldraw_xray import Camera, Session, Style, XrayConfig, compose_mosaic
from ldraw_xray import presets
from ldraw_xray.cli import main, parser
from ldraw_xray.leocad import RenderCall
from ldraw_xray.mpd import Document


@pytest.fixture
def stub_session(fake_lib, tmp_path, monkeypatch):
    class Parts:
        def bounding_box(self, code):
            return SimpleNamespace(min=SimpleNamespace(x=-20, y=-24, z=-10),
                                   max=SimpleNamespace(x=20, y=0, z=10))

    def render(executable, mpd, library, output, *, steps=None, style, **options):
        output.parent.mkdir(parents=True, exist_ok=True)
        count = steps[1] - steps[0] + 1 if steps else 1
        files = []
        for index in range(count):
            path = output.with_stem(f'{output.stem}-{index}')
            Image.new('RGBA', (style.width, style.height), (40 + index, 80, 120, 255)).save(path)
            files.append(path)
        return RenderCall(['fake-leocad'], files, [])

    monkeypatch.setattr('ldraw_xray.render.leocad_render', render)
    monkeypatch.setattr('ldraw_xray.render.parts_index', lambda config: Parts())
    monkeypatch.setattr('ldraw_xray.board.versions', lambda config: {'ldraw_xray': 'test'})
    monkeypatch.setenv('LDRAW_DIR', str(fake_lib))
    monkeypatch.delenv('LDRAW_SHADOW', raising=False)
    monkeypatch.setenv('LEOCAD', '/usr/bin/true')
    config = XrayConfig.resolve(cache_dir=tmp_path / 'cache')
    return Session(config, Style(width=320, height=240))


def test_cli_focused_options_and_config_positions():
    before = parser().parse_args(['--library', '/parts', 'render', 'model.mpd', '-o', 'out'])
    after = parser().parse_args(['render', 'model.mpd', '-o', 'out', '--library', '/parts'])
    assert before.library == after.library == '/parts'
    args = parser().parse_args(['board', 'pivot', 'model.mpd', '--point', '0', '-18', '0',
                               '--direction', '0', '0', '1', '--moving', '!part:3894', '-o', 'out'])
    assert args.point == [0, -18, 0]
    for extra in (['--layer', 'ghost'], ['--out', 'out'], ['--views', 'front'], ['--style', 'width=400']):
        with pytest.raises(ValueError):
            parser().parse_args(['render', 'model.mpd', '-o', 'out', *extra])
    with pytest.raises(ValueError):
        parser().parse_args(['board', 'overview', 'model.mpd', '--angles', '45', '-o', 'out'])
    with pytest.raises(ValueError):
        parser().parse_args(['render', 'model.mpd', '--xray', 'all', '--stud-map', '-o', 'out'])


def test_help_and_error_streams(capsys, monkeypatch):
    with pytest.raises(SystemExit) as status:
        main(['board', 'xray', '--help'])
    assert status.value.code == 0
    captured = capsys.readouterr()
    assert '--select' in captured.out and '--angles' not in captured.out and not captured.err
    assert main(['render']) == 2
    captured = capsys.readouterr()
    assert not captured.out and 'required' in json.loads(captured.err)['error']
    assert main(['render', 'missing.mpd', '--ghost', '-o', 'out']) == 2
    assert 'highlight' in json.loads(capsys.readouterr().err)['error']

    def fail(args):
        raise RuntimeError('LeoCAD failed')

    monkeypatch.setattr('ldraw_xray.cli.run', fail)
    assert main(['doctor']) == 1
    captured = capsys.readouterr()
    assert not captured.out and json.loads(captured.err) == {'error': 'LeoCAD failed'}


def test_doctor_without_dependencies(monkeypatch, capsys):
    for name in ('LDRAW_DIR', 'LDRAWDIR', 'LDRAW_SHADOW', 'LEOCAD'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr('ldraw_xray.config.shutil.which', lambda name: None)
    monkeypatch.setattr('ldraw_xray.config.MAC_LEOCAD', Path('/missing/LeoCAD'))
    assert main(['doctor']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['library'] is None and result['leocad'] is None
    assert not result['renders'] and set(result['errors']) == {'library', 'leocad'}
    assert 'python' in result['versions']


def test_root_defaults_and_minimal_artifacts(stub_session, model, tmp_path):
    output = tmp_path / 'out'
    before = model.read_bytes()
    result = stub_session.render(model, output=output)
    assert result['source']['section'] == 'root.ldr'
    assert {path.name for path in output.iterdir()} == {'panels', 'manifest.json', 'recipe.json'}
    assert model.read_bytes() == before
    panel = result['panels'][0]
    assert panel['view'] == 'home' and (output / panel['image']).is_file()
    assert 'raw' not in panel and 'synthetic' not in panel
    assert panel['raw_sha256'] and panel['synthetic_sha256']
    assert json.loads((output / 'manifest.json').read_text()) == result
    assert json.loads((output / 'recipe.json').read_text())['mosaic'] is False


def test_recipe_replay_from_other_directory(stub_session, model, tmp_path, monkeypatch):
    recipe_path = tmp_path / 'input.json'
    recipe_path.write_text(json.dumps(dict(source=model.name, section='wing.ldr', mosaic=False,
                                          panels=[dict(view='front', layers=[dict(layer='stud_map')])])))
    first = stub_session.board(recipe_path, output=tmp_path / 'first')
    saved = tmp_path / 'first' / 'recipe.json'
    assert json.loads(saved.read_text())['source'] == str(model)
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    second = stub_session.board(saved, output=tmp_path / 'second')
    assert first['panels'] == second['panels']
    assert not (tmp_path / 'second' / 'mosaic.png').exists()


def test_cli_python_and_recipe_equivalence(stub_session, model, tmp_path, capsys):
    # Match CLI defaults to compare complete plans and provenance.
    stub_session.style = Style()
    assert main(['render', str(model), '--section', 'wing.ldr', '--xray', 'colour:14',
                 '--highlight', 'step:3', '--ghost', '--view', 'front', '-o', str(tmp_path / 'cli')]) == 0
    result = json.loads(capsys.readouterr().out)
    assert Path(result['manifest']).is_file() and Path(result['images'][0]['image']).is_file()
    cli_manifest = json.loads(Path(result['manifest']).read_text())
    python_manifest = stub_session.render(model, section='wing.ldr', output=tmp_path / 'python', views=['front'],
                                          layers=[dict(layer='xray', select='colour:14'),
                                                  dict(layer='highlight', select='step:3'), dict(layer='ghost')])
    replay = stub_session.board(result['recipe'], output=tmp_path / 'replay')
    assert cli_manifest['panels'] == python_manifest['panels'] == replay['panels']


def test_intermediates_force_and_unrelated_files(stub_session, model, tmp_path):
    output = tmp_path / 'out'
    old = stub_session.render(model, output=output, views=['home', 'front'], keep_intermediates=True)
    assert all((output / panel['raw']).is_file() and (output / panel['synthetic']).is_file() for panel in old['panels'])
    assert (output / old['source_section']).is_file()
    unrelated = output / 'panels' / 'notes.txt'
    unrelated.write_text('keep me')
    with pytest.raises(ValueError, match='not empty'):
        stub_session.render(model, output=output)
    fresh = stub_session.render(model, output=output, force=True)
    assert unrelated.read_text() == 'keep me'
    assert not (output / 'intermediates').exists()
    assert not (output / old['panels'][1]['image']).exists()
    assert len(fresh['panels']) == 1


@pytest.mark.parametrize('change', [
    {'typo': True},
    {'style': {'widht': 500}},
    {'style': {'width': -10}},
    {'panels': [{'layers': ['ghost']}]},
    {'panels': [{'view': 'sideways'}]},
    {'panels': [{'layers': [{'layer': 'axis', 'direction': [0, 0]}]}]},
    {'panels': [{'layers': [{'layer': 'ghost'}]}]},
    {'panels': [{'layers': [{'layer': 'xray', 'select': 'step:5-2'}]}]},
    {'panels': [{}, {'layers': [{'layer': 'highlight'}]}]},
    {'panels': [{'camera': {'position': [0, 0, 0]}}]},
])
def test_invalid_request_preserves_output(stub_session, model, tmp_path, change, monkeypatch):
    output = tmp_path / 'out'
    output.mkdir()
    original = output / 'manifest.json'
    original.write_text('{"previous": true}')
    recipe = dict(source=str(model), panels=[{}])
    recipe.update(change)
    monkeypatch.setattr('ldraw_xray.render.leocad_render', lambda *a, **kw: pytest.fail('rendered invalid request'))
    with pytest.raises(ValueError):
        stub_session.board(recipe, output=output, force=True)
    assert original.read_text() == '{"previous": true}'
    assert list(output.iterdir()) == [original]


def test_render_failure_preserves_output(stub_session, model, tmp_path, monkeypatch):
    output = tmp_path / 'out'
    stub_session.render(model, output=output)
    before = {path.relative_to(output): path.read_bytes() for path in output.rglob('*') if path.is_file()}

    def fail(*args, **kwargs):
        raise RuntimeError('renderer failed')

    monkeypatch.setattr('ldraw_xray.render.leocad_render', fail)
    with pytest.raises(RuntimeError):
        stub_session.render(model, output=output, force=True)
    assert before == {path.relative_to(output): path.read_bytes() for path in output.rglob('*') if path.is_file()}


def test_mosaic_consumes_saved_and_returned_manifest(stub_session, model, tmp_path):
    result = stub_session.render(model, output=tmp_path / 'out', views=['home', 'front'])
    report = compose_mosaic(tmp_path / 'out' / 'manifest.json', tmp_path / 'one.png')
    other = compose_mosaic(result, tmp_path / 'two.png')
    assert report['image_sha256'] == other['image_sha256']
    board = stub_session.board(presets.overview(model), output=tmp_path / 'board')
    assert (tmp_path / 'board' / board['mosaic']['output']).is_file()
    assert not (tmp_path / 'board' / 'mosaic.json').exists()


def test_parent_ambiguity_and_explicit_choice(model):
    doc = Document.read(model)
    doc.add_block('other.ldr', [
        '1 16 0 0 0 1 0 0 0 1 0 0 0 1 wing.ldr',
        '1 4 100 0 0 1 0 0 0 1 0 0 0 1 3001.dat',
    ])
    model.write_text(doc.text())
    with pytest.raises(ValueError, match='root.ldr, other.ldr'):
        doc.parent_name('wing.ldr')
    with pytest.raises(ValueError, match='--parent'):
        presets.overview(model, 'wing.ldr')
    recipe = presets.overview(model, 'wing.ldr', parent='other.ldr')
    assert recipe['panels'][0]['parent'] == 'other.ldr'
    with pytest.raises(ValueError, match='does not place'):
        doc.parent_name('root.ldr', 'wing.ldr')
    assert all(panel.get('parent') is None for panel in presets.overview(model)['panels'])


def test_every_preset_and_advanced_geometry_layers(stub_session, model, tmp_path):
    recipes = [
        presets.overview(model, 'wing.ldr', steps=[1, 4]),
        presets.stud_map(model, 'wing.ldr', steps='all'),
        presets.xray(model, 'wing.ldr', select='colour:14', highlight='step:3'),
        presets.pivot(model, 'wing.ldr', point=[0, -12, 0], direction=[0, 0, 1], moving='all', hardware='step:3'),
        presets.cutaway(model, 'wing.ldr'),
    ]
    for index, recipe in enumerate(recipes):
        result = stub_session.board(recipe, output=tmp_path / f'preset-{index}')
        assert result['panels'] and 'mosaic' in result
        if index == 3:
            poses = [panel for panel in result['panels'] if any(layer['layer'] == 'pose' for layer in panel['layers'])]
            assert all(panel['camera'] == poses[0]['camera'] for panel in poses)
    advanced = dict(source=str(model), section='wing.ldr', mosaic=False, panels=[
        dict(layers=[dict(layer='recolour', select='all', colour='group:B'),
                     dict(layer='closeup', select='all', view='front')]),
        dict(camera=Camera(position=(100, -100, -100), target=(0, 0, 0)).to_dict()),
    ])
    result = stub_session.board(advanced, output=tmp_path / 'advanced')
    assert result['panels'][0]['layers'][0]['colour'] == 9012
    assert result['panels'][0]['camera']['view'] == 'front'
    assert result['panels'][1]['camera']['position'] == [100, -100, -100]


def test_parent_and_steps_cli(stub_session, model, tmp_path, capsys):
    output = tmp_path / 'context'
    assert main(['render', str(model), '--section', 'wing.ldr', '--parent',
                 '--highlight', 'section', '--ghost', '-o', str(output)]) == 0
    capsys.readouterr()
    result = json.loads((output / 'manifest.json').read_text())
    assert result['panels'][0]['scene']['parent'] == 'root.ldr'
    assert len(result['panels'][0]['parent_placements']) == 2
    output = tmp_path / 'steps'
    assert main(['render', str(model), '--section', 'wing.ldr', '--steps', '1,4', '-o', str(output)]) == 0
    assert [image['step'] for image in json.loads(capsys.readouterr().out)['images']] == [1, 4]
    assert main(['render', str(model), '--section', 'wing.ldr', '--steps',
                 '--highlight', 'all', '-o', str(output)]) == 2
    assert 'source-step' in json.loads(capsys.readouterr().err)['error']
    assert main(['board', 'overview', str(model), '--parent', '-o', str(tmp_path / 'no-parent')]) == 2
    assert 'No parent' in json.loads(capsys.readouterr().err)['error']


def test_fixed_camera_analysis_and_explicit_camera_options(stub_session, model, tmp_path):
    camera = dict(fixed='front')
    recipe = dict(source=str(model), section='wing.ldr', mode='analysis', panels=[
        dict(camera=camera),
        dict(camera=camera, layers=[dict(layer='pose', select='all', angle=45)]),
    ])
    result = stub_session.board(recipe, output=tmp_path / 'analysis')
    assert result['mosaic']['mode'] == 'analysis'
    recipe['panels'][1]['camera'] = {'fixed': 'home'}
    with pytest.raises(ValueError, match='same camera'):
        stub_session.board(recipe, output=tmp_path / 'invalid')
    assert not (tmp_path / 'invalid').exists()
    args = Camera(view='front', orthographic=True, fov=40, zplanes=(1, 1000)).argv()
    assert '--orthographic' in args and args[args.index('--fov') + 1] == '40'
    assert args[-3:] == ['--zplanes', '1.000', '1000.000']


def test_documentation_examples(stub_session, model, tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    readme = (root / 'README.md').read_text()
    reference = (root / 'docs' / 'reference.md').read_text()
    for block in re.findall(r'```sh\n(.*?)```', readme, re.S):
        for line in block.splitlines():
            if line.startswith('ldraw-xray '):
                parser().parse_args(shlex.split(line)[1:])
    monkeypatch.chdir(tmp_path)
    for index, block in enumerate(re.findall(r'```json\n(.*?)```', reference, re.S)):
        value = json.loads(block)
        if 'source' not in value:
            value = dict(source=str(model), section='wing.ldr', panels=[value])
        result = stub_session.board(value, output=tmp_path / f'example-{index}')
        assert result['panels']
    for block in re.findall(r'```python\n(.*?)```', readme, re.S):
        namespace = {}
        exec(block, namespace)
        assert all(image.is_file() for image in namespace['images'])
