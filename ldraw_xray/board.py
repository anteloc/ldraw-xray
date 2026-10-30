"""The shared recipe pipeline: validate, prepare, render, compose, and publish."""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import camera as cam
from .layers import Build, Plan, Scene, apply
from .leocad import Style
from .library import atomic_write
from .manifest import section_text, source_info, versions
from .mosaic import compose_mosaic
from .recipe import load_recipe
from .render import render_panel, slug
from .validation import boolean


@dataclass
class PreparedPanel:
    scene: Scene
    plan: Plan
    camera: cam.Camera
    name: str
    label: str


def _prepare(session, recipe, style):
    """Build every panel before any render or replacement of existing output."""
    fixed, prepared = {}, []
    for index, panel in enumerate(recipe['panels'], 1):
        scene = Scene(Path(recipe['source']), recipe['section'], panel['parent'])
        build = Build(scene, session.parts)
        build.aspect = style.width / style.height
        camera = None
        spec = panel.get('camera')
        if spec is not None:
            if 'fixed' in spec:
                cache_key = (scene.parent, spec['fixed'])
                if cache_key not in fixed:
                    scope = 'parent' if scene.parent else 'section'
                    fixed[cache_key] = cam.framed(
                        build.bounds(scope), spec['fixed'], margin=1.0,
                        note='fixed camera: bounding sphere of the unposed block',
                    )
                camera = fixed[cache_key]
            else:
                camera = cam.Camera.from_dict(spec)
        plan = apply(build, panel['layers']).plan()
        if camera is None:
            if plan.camera is not None:
                camera = plan.camera
            elif plan.bounds is not None:
                camera = cam.fitted(plan.bounds, panel['view'], aspect=style.width / style.height)
            else:
                camera = cam.preset(panel['view'])
        prepared.append(PreparedPanel(scene, plan, camera, f'{index:02d}-{slug(panel["label"])}', panel['label']))
    image_count = sum(len(panel.plan.steps) if panel.plan.steps else 1 for panel in prepared)
    if recipe['mosaic'] and image_count > 12:
        raise ValueError('A mosaic supports at most 12 images; use --no-mosaic or set mosaic to false')
    if recipe['mosaic'] and image_count >= 2 and style.width * style.height > 24_000_000:
        raise ValueError('Mosaic panels must not exceed 24 megapixels')
    if recipe['mosaic'] and recipe['mode'] == 'analysis':
        first = prepared[0]
        if any(panel.camera != first.camera or panel.scene != first.scene for panel in prepared):
            raise ValueError('Analysis panels must use the same camera and subject coordinate frame')
    return prepared


def _previous_files(output):
    """Only files recorded as our artifacts are eligible for removal."""
    owned = {Path('recipe.json'), Path('manifest.json')}
    manifest = output / 'manifest.json'
    if not manifest.is_file():
        return owned
    try:
        previous = json.loads(manifest.read_text())
    except (ValueError, OSError):
        return owned
    if not isinstance(previous, dict):
        return owned
    panels = previous.get('panels', [])
    if not isinstance(panels, list):
        return owned
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        for key in ('image', 'raw', 'synthetic'):
            value = panel.get(key)
            if isinstance(value, str):
                path = Path(value)
                if path.is_absolute():
                    try:
                        path = path.relative_to(output)
                    except ValueError:
                        continue
                if path.parts and path.parts[0] in ('panels', 'intermediates') and '..' not in path.parts:
                    owned.add(path)
    if previous.get('mosaic'):
        owned.add(Path('mosaic.png'))
    if previous.get('source_section'):
        owned.add(Path('intermediates/source-section.ldr'))
    return owned


def _check_output(output, source, library, force):
    if output.is_relative_to(library.resolve()):
        raise ValueError('Output must be outside the LDraw library')
    if output.exists() and not output.is_dir():
        raise ValueError(f'Output must be a directory: {output}')
    if output.exists() and any(output.iterdir()) and not force:
        raise ValueError(f'Output folder is not empty: {output}; use --force to replace generated files')
    for relative in ('panels', 'intermediates', 'intermediates/raw', 'intermediates/synthetic'):
        path = output / relative
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f'Output artifact directory must be a real directory: {path}')
    for relative in _previous_files(output):
        if (output / relative).resolve() == source:
            raise ValueError('Output must not replace the source model')


def _publish(staging, output, source):
    files = [path.relative_to(staging) for path in staging.rglob('*') if path.is_file()]
    previous = _previous_files(output)
    for relative in set(files) | previous:
        target = output / relative
        if target.resolve() == source or target.is_symlink():
            raise ValueError(f'Cannot replace source or symlink: {target}')
        if target.exists() and not target.is_file():
            raise ValueError(f'Artifact path is not a file: {target}')
    output.mkdir(parents=True, exist_ok=True)
    for relative in files:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        (staging / relative).replace(target)
    for relative in previous - set(files):
        (output / relative).unlink(missing_ok=True)
    # Leave unrelated files, including files inside artifact directories, alone.
    intermediates = output / 'intermediates'
    if intermediates.is_dir():
        for directory in sorted(intermediates.rglob('*'), reverse=True):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        if not any(intermediates.iterdir()):
            intermediates.rmdir()


def _legend(recipe, panels):
    lines = list(recipe['legend'])
    swatches = {entry['code']: entry for panel in panels for entry in panel['legend']}
    line = 'Colours:'
    for entry in swatches.values():
        item = f' {entry["value"]} {entry["meaning"]};'
        if len(line) + len(item) > 170:
            lines.append(line.rstrip(';'))
            line = 'Colours:'
        line += item
    if swatches:
        lines.append(line.rstrip(';'))
    if any(panel['step'] is not None or any(layer['layer'] == 'highlight' for layer in panel['layers']) for panel in panels):
        lines.append('Magenta edges: highlighted parts, or parts added in the source step.')
    return lines


def run_board(session, value, output, *, force=False, keep_intermediates=False, mosaic=None):
    boolean(force, 'force')
    boolean(keep_intermediates, 'keep_intermediates')
    recipe = load_recipe(value, session.style)
    if mosaic is not None:
        recipe['mosaic'] = boolean(mosaic, 'mosaic')
    output = Path(output).expanduser().resolve()
    source = Path(recipe['source'])
    style = Style.from_dict(recipe['style'])
    _check_output(output, source, session.config.ldraw_lib, force)
    session.config.require_leocad()
    prepared = _prepare(session, recipe, style)
    # Stage the complete job so renderer or mosaic failures leave old outputs intact.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.xray-', dir=output.parent) as temporary:
        staging = Path(temporary)
        panels = []
        for panel in prepared:
            records = render_panel(session, panel.scene, panel.plan, panel.camera, staging,
                                   name=panel.name, style=style, keep_intermediates=keep_intermediates)
            for record in records:
                suffix = f' — step {record["step"]}' if record['step'] is not None else ''
                record['label'] = panel.label + suffix
                record['subject'] = f'{panel.scene.section}:{panel.scene.parent or "isolated"}'
                panels.append(record)
        manifest = dict(
            output=str(output), recipe='recipe.json', manifest='manifest.json',
            title=recipe['title'], mode=recipe['mode'], panels=panels,
            versions=versions(session.config), source=source_info(source, recipe['section']),
            style=style.to_dict(), legend=_legend(recipe, panels),
            config=dict(library=str(session.config.ldraw_lib), shadows=[str(path) for path in session.config.shadows]),
            synthetic_note='Images come from synthetic inspection copies, not buildable models.',
        )
        if keep_intermediates:
            manifest['source_section'] = 'intermediates/source-section.ldr'
            atomic_write(staging / manifest['source_section'], section_text(source, recipe['section']))
        if recipe['mosaic'] and len(panels) >= 2:
            report = compose_mosaic(
                {**manifest, 'base': str(staging)}, staging / 'mosaic.png',
                columns=recipe['columns'], panel_width=recipe['panel_width'], write_sidecar=False,
            )
            report['output'] = 'mosaic.png'
            for entry in report['panels']:
                entry['image'] = str(Path(entry['image']).relative_to(staging))
            manifest['mosaic'] = report
        atomic_write(staging / 'recipe.json', json.dumps(recipe, indent=2) + '\n')
        atomic_write(staging / 'manifest.json', json.dumps(manifest, indent=2) + '\n')
        _publish(staging, output, source)
    return manifest


def summary(manifest):
    """Absolute paths for CLI consumers; saved manifests use portable relative paths."""
    output = Path(manifest['output'])
    result = dict(
        output=str(output), recipe=str(output / manifest['recipe']), manifest=str(output / manifest['manifest']),
        images=[dict(image=str(output / panel['image']), shows=panel['label'], view=panel['view'],
                     step=panel['step'], notes=panel['notes'], warnings=panel['warnings']) for panel in manifest['panels']],
    )
    if 'mosaic' in manifest:
        result['mosaic'] = str(output / manifest['mosaic']['output'])
        result['duplicate_panels'] = manifest['mosaic']['duplicates']
    return result
