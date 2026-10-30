"""Boards: a JSON recipe of panels -> renders + manifest + mosaic.

Recipe:
{
  "title": "...", "source": "model.mpd", "section": "name.ldr", "parent": null,
  "mode": "views", "columns": 2, "panel_width": 800, "style": {...Style overrides},
  "legend": ["optional extra legend lines"],
  "panels": [
    {"label": "...", "context": "isolate" | "parent", "layers": ["xray:sel=colour:15", ...],
     "view": "home"}                      # or "camera": {...explicit} or "camera": {"fixed": "home"}
  ]
}
`{"fixed": VIEW}` frames the rendered block's unposed bounds, so every panel that
uses it shares one camera (pose sweeps, before/after comparisons).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import camera as cam
from .layers import Build, Scene
from .leocad import Style
from .library import atomic_write
from .manifest import section_text, source_info, versions
from .mosaic import compose_mosaic
from .render import Session, slug


def _source(recipe, base):
    path = Path(recipe['source'])
    return path if path.is_absolute() else (base / path).resolve()


def run_board(recipe, out_dir, *, session: Session | None = None, base='.', force=False, mosaic=True):
    """Render every panel of `recipe` into `out_dir`; returns the board manifest."""
    session = session or Session()
    base, out_dir = Path(base).resolve(), Path(out_dir).resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        if not force:
            raise ValueError(f'Output folder is not empty: {out_dir} (use force)')
        # Only what a board writes is removed; anything else in the folder stays.
        shutil.rmtree(out_dir / 'panels', ignore_errors=True)
        for name in ('mosaic.png', 'mosaic.json', 'manifest.json', 'recipe.json', 'source-section.ldr'):
            (out_dir / name).unlink(missing_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    source = _source(recipe, base)
    style = Style.from_dict({**session.style.to_dict(), **recipe.get('style', {})})
    atomic_write(out_dir / 'recipe.json', json.dumps(recipe, indent=2) + '\n')
    atomic_write(out_dir / 'source-section.ldr', section_text(source, recipe['section']))
    fixed = {}
    panels, images = [], []
    for n, panel in enumerate(recipe['panels'], 1):
        scene = Scene(source, recipe['section'], panel.get('context', 'isolate'), panel.get('parent', recipe.get('parent')))
        cameras = None
        spec = panel.get('camera')
        if isinstance(spec, dict) and 'fixed' in spec:
            k = (scene.context, scene.parent, spec['fixed'])
            if k not in fixed:
                build = Build(scene, session.parts)
                fixed[k] = cam.framed(build.bounds('parent' if build.parent else 'section'), spec['fixed'], margin=1.0,
                                      note='fixed camera: bounding sphere of the unposed block')
            cameras = [fixed[k]]
        elif isinstance(spec, dict):
            cameras = [cam.Camera.from_dict(spec)]
        records = session.render(scene, panel.get('layers', []), [panel.get('view', 'home')], out_dir / 'panels',
                                 name=f'{n:02d}-{slug(panel["label"])}', cameras=cameras, style=style)
        if len(records) != 1:
            raise ValueError(f'Panel {n} produced {len(records)} images; a panel must render exactly one (one view, one step)')
        record = records[0]
        record['label'] = panel['label']
        panels.append(record)
        images.append(dict(image=str(Path(record['image']).relative_to(out_dir)), label=panel['label'],
                           camera=record['camera'], subject=f'{scene.context}:{record["submodel"]}'))
    legend = list(recipe.get('legend', []))
    seen = {}
    for record in panels:
        for entry in record['legend']:
            seen[entry['code']] = f'{entry["value"]} {entry["meaning"]}'
    line = 'Colours:'
    for item in seen.values():
        if len(line) + len(item) > 170:
            legend.append(line)
            line = '  '
        line += ' ' + item + ';'
    if seen:
        legend.append(line.rstrip(';'))
    if any(any(l['layer'] == 'highlight' for l in r['layers']) or r['step'] for r in panels):
        legend.append('Magenta edges: highlighted parts (new in the step, or selected).')
    manifest = dict(versions=versions(session.config), source=source_info(source, recipe['section']), style=style.to_dict(),
                    config=dict(ldraw_lib=str(session.config.ldraw_lib), shadows=[str(s) for s in session.config.shadows]),
                    panels=panels, synthetic_note='Images come from synthetic copies; they are not valid models.')
    if mosaic and len(images) >= 2:
        board = dict(title=recipe.get('title', 'Inspection board'), mode=recipe.get('mode', 'views'),
                     panels=images, legend=[_short(l) for l in legend], base=str(out_dir))
        manifest['mosaic'] = compose_mosaic(board, out_dir / 'mosaic.png', columns=recipe.get('columns', 2),
                                            panel_width=recipe.get('panel_width', 800), force=True)
    atomic_write(out_dir / 'manifest.json', json.dumps(manifest, indent=2, default=str) + '\n')
    return manifest


def _short(line, limit=180):
    return line if len(line) <= limit else line[:limit - 1] + '…'


def summary(manifest):
    """Compact agent-facing result: what to open and what each image shows."""
    out = dict(images=[dict(image=p['image'], shows=p['label'], view=p['view'], step=p['step'],
                            notes=p['notes'] or None, warnings=p['warnings'] or None) for p in manifest['panels']])
    if 'mosaic' in manifest:
        out['mosaic'] = manifest['mosaic']['output']
        if manifest['mosaic']['duplicates']:
            out['duplicate_panels'] = manifest['mosaic']['duplicates']
    return out
