"""LeoCAD as an external renderer, with every visual setting pinned.

The LeoCAD CLI falls back to the GUI preferences for anything not passed, so
renders would differ between machines. Every argument that affects pixels is
passed explicitly here.

Measured on LeoCAD 25.09 (see docs/reference.md):
- edge-colour options (-ec/-bec/-dec/-scc/-aec/-cc/-ldv) are ignored unless the
  stud style is 6 or 7 (LeoCAD warns but still exits 0);
- `-i` writes RGBA PNGs with a transparent background;
- `--highlight` draws parts of the rendered step with highlight-coloured edges;
  `--fade-steps` replaces earlier steps' colours with the fade colour;
- `--zplanes NEAR FAR` clips at a plane perpendicular to the view direction.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import ImageColor

from .validation import boolean, choice, fields, number

TESTED_VERSIONS = ('25.09',)
BENIGN = ('Saved ', 'High contrast stud and edge color settings are ignored when -aec')
NEEDS_HC = 'High contrast stud style is required'


@dataclass(frozen=True)
class Style:
    """Pinned render settings. The defaults are the measured 'contrast pack'."""

    width: int = 1200
    height: int = 900
    stud_style: int = 6
    auto_edges: bool = True
    edge_contrast: float = 1.0
    light_dark: float = 0.5
    line_width: float = 2
    aa_samples: int = 4
    shading: str = 'full'
    highlight: str = '#FFFF00FF'      # LeoCAD #AARRGGBB: opaque magenta
    fade: str = '#40C0C0C0'           # 25% light grey ghost
    backdrop: str = '#EEF1F4'         # flatten colour (post-processing)
    outline: str | None = '#2A2F36'   # alpha-traced outline colour; None disables
    outline_width: int = 2

    def __post_init__(self):
        for name in ('width', 'height'):
            number(getattr(self, name), name, integer=True, positive=True)
        for name in ('stud_style', 'aa_samples', 'outline_width'):
            number(getattr(self, name), name, integer=True, minimum=0)
        number(self.stud_style, 'stud_style', maximum=7)
        if self.aa_samples not in (1, 2, 4, 8):
            raise ValueError('aa_samples must be 1, 2, 4, or 8')
        for name in ('edge_contrast', 'light_dark'):
            number(getattr(self, name), name, minimum=0, maximum=1)
        number(self.line_width, 'line_width', positive=True)
        boolean(self.auto_edges, 'auto_edges')
        choice(self.shading, ('wireframe', 'flat', 'default', 'full'), 'shading')
        for name in ('highlight', 'fade'):
            if not isinstance(getattr(self, name), str) or not re.fullmatch(r'#[0-9a-fA-F]{8}', getattr(self, name)):
                raise ValueError(f'{name} must be #AARRGGBB')
        for name in ('backdrop', 'outline'):
            value = getattr(self, name)
            if name == 'outline' and value is None:
                continue
            if not isinstance(value, str):
                raise ValueError(f'{name} must be a colour string')
            ImageColor.getrgb(value)

    def argv(self):
        args = ['-w', str(self.width), '-h', str(self.height), '--aa-samples', str(self.aa_samples),
                '--shading', self.shading, '--line-width', f'{self.line_width:g}', '--stud-style', str(self.stud_style),
                '--highlight-color', self.highlight, '--fade-steps-color', self.fade]
        if self.auto_edges:
            args += ['-aec', '-cc', f'{self.edge_contrast:g}', '-ldv', f'{self.light_dark:g}']
        return args

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**fields(data, cls.__dataclass_fields__, name='style'))


def version(executable):
    r = subprocess.run([str(executable), '-v'], capture_output=True, text=True, timeout=60)
    m = re.search(r'LeoCAD Version\s+(\S+)', r.stdout + r.stderr)
    return m.group(1) if m else None


@dataclass
class RenderCall:
    argv: list[str]
    outputs: list[Path]
    warnings: list[str]


def render(executable, mpd, library, output, *, style: Style, camera_args, submodel=None,
           steps=None, highlight=False, fade=False, timeout=300):
    """Render one image, or one image per step when `steps=(first, last)` spans several.

    Returns the produced files in step order. LeoCAD names multi-step outputs
    `<stem><NN>.png`; a single step may keep the plain name.
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    argv = [str(executable), '-l', str(library), '-i', str(output), *style.argv(), *camera_args]
    if submodel:
        argv += ['--submodel', submodel]
    if steps:
        argv += ['--from', str(steps[0]), '--to', str(steps[1])]
    argv += ['--highlight' if highlight else '--no-highlight', '--fade-steps' if fade else '--no-fade-steps', str(mpd)]
    before = {p: p.stat().st_mtime_ns for p in output.parent.glob(output.stem + '*.png')}
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    lines = [l for l in (r.stdout + r.stderr).splitlines() if l.strip() and not l.startswith(BENIGN)]
    if r.returncode:
        raise RuntimeError(f'LeoCAD failed ({r.returncode}): ' + '\n'.join(lines))
    if any(NEEDS_HC in l for l in lines) and style.stud_style not in (6, 7):
        lines.append('Edge-colour settings were ignored: they need stud_style 6 or 7')
    pattern = re.compile(re.escape(output.stem) + r'(\d*)\.png$')
    produced = sorted((p for p in output.parent.glob(output.stem + '*.png')
                       if pattern.fullmatch(p.name) and before.get(p) != p.stat().st_mtime_ns),
                      key=lambda p: int(pattern.fullmatch(p.name).group(1) or 0))
    if not produced:
        raise RuntimeError('LeoCAD reported success but wrote no image: ' + '\n'.join(lines))
    return RenderCall(argv, produced, lines)
