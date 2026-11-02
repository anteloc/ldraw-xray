"""Translate the historical panel specifications to ordinary xray recipes.

This is validation data preparation, not a renderer: no nova imports, geometry
rewrites, image processing, or LeoCAD calls. Recipes also run directly via CLI.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess

from ldraw_xray.mpd import Document

HERE = Path(__file__).resolve().parent
XRAY = HERE.parents[1]
NOVA = XRAY.parent / 'ldraw-nova'
ORIGINALS = NOVA / 'output/submodel-candidates'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def camera(value):
    return dict(position=value.get('camera_position_ldraw', value.get('position_ldraw')),
                target=value['target_ldraw'], up=value['up_ldraw'], fov=value['fov'])


def main():
    cases = []
    inputs = set()
    for info_path in sorted(ORIGINALS.rglob('info.json')):
        folder = info_path.parent
        info = json.loads(info_path.read_text())
        old = json.loads((folder / 'panels.json').read_text())
        source = NOVA / info['source']
        doc = Document.read(source)
        nonempty = sorted({p.step for p in doc.block(info['section']).placements()})
        case_id = folder.name
        panels, mappings, differences = [], [], []
        for original in old['panels']:
            relative = original['image']
            label = original['label'].replace(' (flattened on white)', '')
            panel = dict(label=label, layers=[])
            mapping = dict(original=relative)
            path = Path(relative)
            view = re.match(r'^(home|front|back|left|right|top|bottom)', path.stem)
            if view:
                panel['view'] = view[1]
            if relative.startswith('parent-closeup/'):
                cam_path = folder / 'parent-closeup/camera.json'
                inputs.add(cam_path)
                panel.update(parent=info['parent'], camera=camera(json.loads(cam_path.read_text())))
                panel['layers'] = [dict(layer='highlight', select='section')]
                if 'ghost' in relative:
                    panel['layers'].append(dict(layer='ghost'))
            elif relative.startswith(('parent/', 'parent-ghost/')):
                panel['parent'] = info['parent']
                panel['layers'] = [dict(layer='highlight', select='section')]
                if relative.startswith('parent-ghost/'):
                    panel['layers'].append(dict(layer='ghost'))
            elif relative.startswith('steps/'):
                dense = int(re.search(r'(\d+)\.png$', relative)[1])
                source_step = nonempty[dense - 1]
                panel['layers'] = [dict(layer='steps', numbers=[source_step])]
                mapping.update(original_rendered_step=dense, source_step=source_step)
                if source_step != dense:
                    differences.append(f'{relative}: LeoCAD image {dense} corresponds to source step {source_step} (empty steps).')
            elif relative.startswith('orientation/'):
                panel['layers'] = [dict(layer='stud_map')]
            elif relative.startswith('iso/'):
                pass
            elif relative.startswith('core/'):
                panel['layers'] = [dict(layer='xray', select='!step:3')]
            elif relative.startswith('pivot/'):
                axis = dict(layer='axis', point=[0, -18, 0], direction=[0, 0, 1], length=230, radius=2)
                if 'parent-' in relative:
                    panel.update(parent=info['parent'], view='home')
                    axis.update(length=340, radius=5)
                    panel['layers'] = [dict(layer='highlight', select='section'), dict(layer='ghost'), axis]
                else:
                    panel['layers'] = [axis, dict(layer='highlight', select='part:43093|part:3894')]
                    if 'pose-' in relative:
                        angle = int(re.search(r'pose-(\d+)', relative)[1])
                        panel['layers'].insert(0, dict(layer='pose', select='!part:3894',
                                                     point=[0, -18, 0], direction=[0, 0, 1], angle=angle))
                        pose_data = json.loads((folder / 'pivot/poses-panels.json').read_text())
                        panel['camera'] = camera(pose_data['panels'][0]['camera'])
                        inputs.add(folder / 'pivot/poses-panels.json')
            elif relative.startswith('ring/'):
                # The current API cannot remove arbitrary parent placements. Keep
                # this attempt explicit; do not reuse Claude's synthetic extract.
                selected = [p.line for p in doc.block(info['parent']).placements()
                            if p.ref in (info['section'], '21309 - 103-107.ldr')]
                selector = 'line:' + ','.join(map(str, selected))
                panel.update(parent=info['parent'], view='top')
                panel['layers'] = []
                if 'orientation' in relative:
                    panel['layers'].append(dict(layer='stud_map', select=selector, scope='parent'))
                panel['layers'] += [dict(layer='highlight', select=selector, scope='parent'),
                                    dict(layer='ghost'), dict(layer='closeup', select=selector,
                                                             scope='parent', view='top')]
                panel['label'] = ('Approximation: hub and eight panels in ghosted parent; '
                                  + ('stud map in parent coordinates' if 'orientation' in relative else 'top close-up'))
                mapping['limitation'] = 'No isolate-selection/extract layer; surrounding parent remains ghosted.'
                differences.append(relative + ': ' + mapping['limitation'])
            else:
                raise ValueError(relative)
            panels.append(panel)
            mappings.append(mapping)
            inputs.add(folder / relative)
        recipe = dict(source=str(source.relative_to(NOVA.parent)), section=info['section'],
                      title=old['title'], panels=panels)
        # Resolve from recipes/, so the committed fixtures work in sibling repos.
        recipe['source'] = '../../../../' + recipe['source']
        recipe_path = HERE / 'recipes' / (case_id + '.json')
        write(recipe_path, recipe)
        cases.append(dict(id=case_id, recipe=str(recipe_path.relative_to(HERE)),
                          original=str(folder.relative_to(NOVA)), source=info['source'],
                          section=info['section'], original_source_sha256=info['source_sha256'],
                          panels=mappings, differences=differences))
        inputs.update((info_path, folder / 'panels.json', folder / 'mosaic.png', source))
        orientation = folder / 'orientation/stud-directions.json'
        if orientation.exists():
            inputs.add(orientation)

    base = next(c for c in cases if c['id'].startswith('07-'))
    original = NOVA / base['original'] / 'pivot/poses-panels.json'
    spec = json.loads(original.read_text())
    pose_recipe = dict(source=json.loads((HERE / base['recipe']).read_text())['source'],
                       section=base['section'], title=spec['title'], mode='analysis', columns=3,
                       panel_width=640, panels=[])
    for angle, p in zip((0, 45, 90), spec['panels']):
        pose_recipe['panels'].append(dict(label=p['label'], camera=camera(p['camera']), layers=[
            dict(layer='pose', select='!part:3894', point=[0, -18, 0], direction=[0, 0, 1], angle=angle),
            dict(layer='axis', point=[0, -18, 0], direction=[0, 0, 1], length=230, radius=2),
            dict(layer='highlight', select='part:43093|part:3894')]))
    pose_id = '07-75060-pose-sweep'
    write(HERE / 'recipes' / (pose_id + '.json'), pose_recipe)
    cases.append(dict(id=pose_id, recipe=f'recipes/{pose_id}.json',
                      original=base['original'] + '/pivot', original_mosaic='poses-mosaic.png',
                      source=base['source'], section=base['section'],
                      panels=[dict(original=p['image']) for p in spec['panels']], differences=[]))
    inputs.update([original, original.parent / 'poses-mosaic.png',
                   *(original.parent / p['image'] for p in spec['panels'])])
    write(HERE / 'cases.json', cases)
    inputs.update(NOVA / p for p in subprocess.check_output(
        ['git', '-C', str(NOVA), 'diff', '--name-only'], text=True).splitlines())
    inputs.update(NOVA / p for p in subprocess.check_output(
        ['git', '-C', str(NOVA), 'ls-files', '--others', '--exclude-standard'], text=True).splitlines())
    snapshot = dict(xray_commit=subprocess.check_output(['git', '-C', str(XRAY), 'rev-parse', 'HEAD'], text=True).strip(),
                    nova_status=subprocess.check_output(['git', '-C', str(NOVA), 'status', '--porcelain'], text=True),
                    inputs={str(p.relative_to(NOVA)): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sorted(inputs) if p.is_file()})
    write(HERE / 'evidence/before.json', snapshot)
    print(f'Prepared {len(cases)} recipes; recorded {len(snapshot["inputs"])} input hashes.')


if __name__ == '__main__':
    main()
