"""Render a scene with layers: synthetic MPD -> LeoCAD -> flattened PNGs + records."""
from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from . import camera as cam
from .config import XrayConfig
from .layers import Build, Scene, apply
from .leocad import Style, render as leocad_render
from .library import atomic_write, parts_index, render_library
from .post import coverage, flatten

def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', str(text).casefold()).strip('-')[:60] or 'panel'


class Session:
    """Holds configuration and the (lazily built) pyldraw3 parts index across renders."""

    def __init__(self, config: XrayConfig | None = None, style: Style | None = None):
        self.config = config or XrayConfig.from_env()
        self.style = style or Style()
        self._parts = None

    @property
    def parts(self):
        if self._parts is None:
            self._parts = parts_index(self.config)
        return self._parts

    def render(self, scene: Scene, layers=(), views=('home',), out_dir='.', *, name=None, cameras=None, style=None):
        """Render `scene` with `layers` from each view (or explicit `cameras`).

        Returns one record per written image: flattened `image`, transparent `raw`,
        camera, step, layers, legend, LeoCAD argv, warnings and notes.
        """
        style = style or self.style
        out_dir = Path(out_dir)
        build = Build(scene, self.parts)
        build.aspect = style.width / style.height
        plan = apply(build, layers).plan()
        name = name or slug(f'{scene.section}-{scene.context}')
        synthetic = out_dir / 'synthetic' / f'{name}.mpd'
        atomic_write(synthetic, plan.doc.text())
        executable = self.config.require_leocad()
        shots = []
        if cameras:
            shots = [(c.view or f'camera{i}', c) for i, c in enumerate(cameras)]
        elif plan.camera is not None:
            shots = [(plan.camera.view or 'camera', plan.camera)]
        elif plan.bounds is not None:
            shots = [(v, cam.fitted(plan.bounds, v, aspect=style.width / style.height)) for v in views]
        else:
            shots = [(v, cam.preset(v)) for v in views]
        records = []
        with tempfile.TemporaryDirectory(prefix='xray-') as tmp:
            mpd, library, renamed = render_library(self.config, plan.doc, Path(tmp))
            for label, camera in shots:
                if plan.steps:
                    ranges = [(plan.steps[0][1], plan.steps[-1][1])]
                elif plan.final_step:
                    ranges = [(plan.final_step, plan.final_step)]
                else:
                    ranges = [None]
                for rng in ranges:
                    target = Path(tmp) / 'out' / f'{label}.png'
                    call = leocad_render(executable, mpd, library, target, style=style, camera_args=camera.argv(),
                                         submodel=plan.submodel, steps=rng, highlight=plan.highlight, fade=plan.fade)
                    step_names = [s for s, _ in plan.steps] if plan.steps else [None]
                    if plan.steps and len(call.outputs) != len(step_names):
                        raise RuntimeError(f'Expected {len(step_names)} step images, LeoCAD wrote {len(call.outputs)}')
                    for produced, step in zip(call.outputs, step_names):
                        stem = f'{name}-{label}' + (f'-s{step:02d}' if step is not None else '')
                        raw = out_dir / 'raw' / f'{stem}.png'
                        raw.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(produced, raw)
                        with Image.open(raw) as im:
                            rgba = im.convert('RGBA')
                        image = out_dir / f'{stem}.png'
                        flatten(rgba, style.backdrop, style.outline, style.outline_width).save(image)
                        records.append(dict(
                            image=str(image), raw=str(raw), view=label, step=step, camera=camera.to_dict(),
                            scene=scene.to_dict(), layers=plan.records, legend=plan.legend, notes=plan.notes,
                            synthetic=str(synthetic), synthetic_sha256=hashlib.sha256(synthetic.read_bytes()).hexdigest(),
                            submodel=plan.submodel, parent_placements=plan.parent_placements,
                            materialized_parts=renamed, coverage=coverage(rgba),
                            argv=[a.replace(tmp, '<tmp>') for a in call.argv], warnings=call.warnings,
                            style=style.to_dict()))
        return records
