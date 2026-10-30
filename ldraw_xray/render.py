"""Render prepared panels through LeoCAD; expose one session API for all jobs."""
from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from .camera import Camera
from .config import XrayConfig
from .layers import Layer, Plan, Scene
from .leocad import Style, render as leocad_render
from .library import atomic_write, parts_index, render_library
from .post import coverage, flatten


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', str(text).casefold()).strip('-')[:60] or 'panel'


class Session:
    """Configuration and a lazily loaded parts index, reusable across render jobs."""

    def __init__(self, config: XrayConfig | None = None, style: Style | None = None):
        self.config = config or XrayConfig.from_env()
        self.style = style or Style()
        self._parts = None

    @property
    def parts(self):
        if self._parts is None:
            self._parts = parts_index(self.config)
        return self._parts

    def render(self, source: str | Path, *, output: str | Path, section: str | None = None,
               parent: str | None = None, layers: list[Layer] | tuple = (),
               views: list[str] | tuple[str, ...] = ('home',), cameras: list[Camera] | None = None,
               style: Style | None = None, force=False, keep_intermediates=False) -> dict[str, Any]:
        """Render a model or section and return its manifest. See ``recipe.json`` to replay it."""
        if not isinstance(views, (list, tuple)) or not views:
            raise ValueError('views must be a nonempty list of view names')
        if not isinstance(layers, (list, tuple)):
            raise ValueError('layers must be a list of objects')
        panels = []
        if cameras is not None:
            if not isinstance(cameras, (list, tuple)) or not cameras or not all(isinstance(c, Camera) for c in cameras):
                raise ValueError('cameras must be a nonempty list of Camera objects')
            for index, camera in enumerate(cameras, 1):
                panels.append(dict(label=f'Camera {index}', camera=camera.to_dict(),
                                   parent=parent, layers=list(layers)))
        else:
            for view in views:
                panels.append(dict(label=f'{view} view', view=view, parent=parent, layers=list(layers)))
        recipe = dict(source=str(source), section=section, panels=panels, mosaic=False)
        if style is not None:
            recipe['style'] = style.to_dict()
        return self.board(recipe, output=output, force=force, keep_intermediates=keep_intermediates)

    def board(self, recipe, *, output: str | Path, force=False, keep_intermediates=False,
              mosaic: bool | None = None) -> dict[str, Any]:
        """Run a recipe mapping or JSON file and return its manifest."""
        from .board import run_board
        return run_board(self, recipe, output, force=force,
                         keep_intermediates=keep_intermediates, mosaic=mosaic)


def _step_batches(plan: Plan):
    """Group consecutive rendered steps without accidentally rendering unrequested steps."""
    if not plan.steps:
        bounds = (plan.final_step, plan.final_step) if plan.final_step else None
        return [(bounds, [None])]
    batches = []
    for source_step, rendered_step in plan.steps:
        if batches and batches[-1][0][1] + 1 == rendered_step:
            bounds, sources = batches[-1]
            batches[-1] = ((bounds[0], rendered_step), [*sources, source_step])
        else:
            batches.append(((rendered_step, rendered_step), [source_step]))
    return batches


def render_panel(session: Session, scene: Scene, plan: Plan, camera: Camera,
                 directory: Path, *, name: str, style: Style, keep_intermediates: bool) -> list[dict]:
    """Write one prepared panel's images into a staging directory, using relative artifact paths."""
    synthetic_text = plan.doc.text()
    synthetic_hash = hashlib.sha256(synthetic_text.encode()).hexdigest()
    synthetic = Path('intermediates') / 'synthetic' / f'{name}.mpd'
    if keep_intermediates:
        atomic_write(directory / synthetic, synthetic_text)
    records = []
    view = camera.view or 'camera'
    with tempfile.TemporaryDirectory(prefix='xray-render-') as temporary:
        temporary = Path(temporary)
        mpd, library, renamed = render_library(session.config, plan.doc, temporary)
        for index, (bounds, source_steps) in enumerate(_step_batches(plan)):
            call = leocad_render(
                session.config.require_leocad(), mpd, library, temporary / 'out' / f'{index}.png',
                style=style, camera_args=camera.argv(), submodel=plan.submodel,
                steps=bounds, highlight=plan.highlight, fade=plan.fade,
            )
            if len(call.outputs) != len(source_steps):
                raise RuntimeError(f'Expected {len(source_steps)} images, LeoCAD wrote {len(call.outputs)}')
            for produced, step in zip(call.outputs, source_steps):
                stem = name + (f'-s{step:02d}' if step is not None else '')
                with Image.open(produced) as image:
                    rgba = image.convert('RGBA')
                image_path = Path('panels') / f'{stem}.png'
                (directory / 'panels').mkdir(exist_ok=True)
                flatten(rgba, style.backdrop, style.outline, style.outline_width).save(directory / image_path)
                record = dict(
                    image=str(image_path), view=view, step=step, camera=camera.to_dict(),
                    scene=scene.to_dict(), layers=plan.records, legend=plan.legend, notes=plan.notes,
                    synthetic_sha256=synthetic_hash, raw_sha256=hashlib.sha256(produced.read_bytes()).hexdigest(),
                    image_sha256=hashlib.sha256((directory / image_path).read_bytes()).hexdigest(),
                    submodel=plan.submodel, parent_placements=plan.parent_placements,
                    materialized_parts=renamed, coverage=coverage(rgba),
                    argv=[arg.replace(str(temporary), '<tmp>') for arg in call.argv], warnings=call.warnings,
                    style=style.to_dict(),
                )
                if keep_intermediates:
                    raw_path = Path('intermediates') / 'raw' / f'{stem}.png'
                    (directory / raw_path).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(produced, directory / raw_path)
                    record.update(raw=str(raw_path), synthetic=str(synthetic))
                records.append(record)
    return records
