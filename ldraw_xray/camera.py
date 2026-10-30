"""Cameras: LeoCAD preset viewpoints, explicit framing, close-ups and cutaways.

All explicit cameras use LDraw coordinates (`--camera-position-ldraw`); -Y is up
and the front view looks toward +Z.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from .validation import boolean, fields, number, vector

VIEWS = ('home', 'front', 'back', 'left', 'right', 'top', 'bottom')
# From the target toward the camera, matching LeoCAD's --viewpoint names (measured on
# 25.09): `right` shows the model's right side from -X, `left` its left side from +X.
DIRECTIONS = {'home': (1, -1, -1), 'front': (0, 0, -1), 'back': (0, 0, 1), 'left': (1, 0, 0),
              'right': (-1, 0, 0), 'top': (0, -1, 0), 'bottom': (0, 1, 0)}


@dataclass(frozen=True)
class Camera:
    """Either a LeoCAD viewpoint (auto-framed) or an explicit camera."""

    view: str | None = None
    position: tuple[float, float, float] | None = None
    target: tuple[float, float, float] | None = None
    up: tuple[float, float, float] = (0.0, -1.0, 0.0)
    fov: float = 30.0
    orthographic: bool = False
    zplanes: tuple[float, float] | None = None
    note: str = ''

    def __post_init__(self):
        if self.view is not None and self.view not in VIEWS:
            raise ValueError(f'Unknown view {self.view!r}; use one of {", ".join(VIEWS)}')
        number(self.fov, 'camera fov', positive=True, maximum=179)
        boolean(self.orthographic, 'camera orthographic')
        up = np.asarray(vector(self.up, 'camera up', nonzero=True))
        if (self.position is None) != (self.target is None):
            raise ValueError('Explicit cameras need both position and target')
        if self.position is not None:
            position = np.asarray(vector(self.position, 'camera position'))
            target = np.asarray(vector(self.target, 'camera target'))
            if np.linalg.norm(np.cross(target - position, up)) < 1e-12:
                raise ValueError('Camera position and target must differ, and up must not parallel the view')
        if self.zplanes is not None:
            near, far = vector(self.zplanes, 'camera zplanes', size=2)
            if not 1 <= near < far:
                raise ValueError('camera zplanes must satisfy 1 <= near < far')
        if not isinstance(self.note, str):
            raise ValueError('camera note must be text')

    def argv(self):
        args = ['--fov', f'{self.fov:g}']
        if self.position is None:
            args += ['--viewpoint', self.view or 'home']
        else:
            args += ['--camera-position-ldraw',
                     *(f'{v:.4f}' for v in (*self.position, *self.target, *self.up))]
        if self.orthographic:
            args.append('--orthographic')
        if self.zplanes:
            args += ['--zplanes', f'{self.zplanes[0]:.3f}', f'{self.zplanes[1]:.3f}']
        return args

    def to_dict(self):
        return {key: list(value) if isinstance(value, tuple) else value
                for key, value in asdict(self).items() if value not in (None, '', ())}

    @classmethod
    def from_dict(cls, data):
        data = fields(data, cls.__dataclass_fields__, name='camera')
        for k in ('position', 'target', 'up', 'zplanes'):
            if data.get(k) is not None:
                data[k] = vector(data[k], f'camera {k}', size=2 if k == 'zplanes' else 3)
        return cls(**data)


def preset(view):
    if view not in VIEWS:
        raise ValueError(f'Unknown view {view!r}; use one of {", ".join(VIEWS)}')
    return Camera(view=view)


def _up(view):
    return (0.0, 0.0, 1.0) if view == 'top' else (0.0, 0.0, -1.0) if view == 'bottom' else (0.0, -1.0, 0.0)


def framed(bounds, view='home', *, fov=30.0, margin=1.15, note='framed on bounding sphere'):
    """Fit the bounding sphere of `bounds`: loose, but nothing rotating inside it leaves the frame (pose sweeps)."""
    centre = bounds.centre
    radius = max(1.0, float(np.linalg.norm(bounds.size)) / 2)
    direction = np.array(DIRECTIONS[view], float)
    direction /= np.linalg.norm(direction)
    distance = radius / math.sin(math.radians(fov / 2)) * margin
    return Camera(view=view, position=tuple(map(float, centre + direction * distance)), target=tuple(map(float, centre)),
                  up=_up(view), fov=fov, note=note)


def fitted(bounds, view='home', *, fov=30.0, aspect=4 / 3, margin=1.08, note='fitted to part corners'):
    """Tightest perspective fit of the parts' box corners (or the 8 box corners); fov is vertical, as in LeoCAD."""
    centre = bounds.centre
    back = np.array(DIRECTIONS[view], float)
    back /= np.linalg.norm(back)                       # from the target toward the camera
    up = -np.array(_up(view), float)                   # LDraw up vector is -Y; screen up is +up
    right = np.cross(back, up)
    right /= np.linalg.norm(right)
    up = np.cross(right, back)
    tan_v = math.tan(math.radians(fov / 2))
    tan_h = tan_v * aspect
    lo, hi = bounds.low, bounds.high
    points = bounds.points if bounds.points is not None else np.array(
        [[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    rel = np.asarray(points, float) - centre
    depth = rel @ back
    distance = max(1.0, float(np.max(depth + np.abs(rel @ right) / tan_h * margin)),
                   float(np.max(depth + np.abs(rel @ up) / tan_v * margin)))
    return Camera(view=view, position=tuple(map(float, centre + back * distance)), target=tuple(map(float, centre)),
                  up=_up(view), fov=fov, note=note)


def cutaway(bounds, view='front', depth=0.5, *, fov=30.0, aspect=4 / 3, margin=1.08):
    """Axis-aligned view whose near plane cuts the model at `depth` (0 = nearest face, 1 = farthest).

    LeoCAD's near plane is perpendicular to the view direction, so only the six
    axis-aligned views give a planar section of the model.
    """
    if view == 'home':
        raise ValueError('Cutaways need an axis-aligned view (front, back, left, right, top, bottom)')
    if not 0.0 <= depth <= 1.0:
        raise ValueError('Cutaway depth must be between 0 and 1')
    cam = fitted(bounds, view, fov=fov, aspect=aspect, margin=margin)
    position, centre = np.array(cam.position), bounds.centre
    look = (centre - position) / np.linalg.norm(centre - position)
    axis = int(np.argmax(abs(look)))
    near_face = bounds.low[axis] if look[axis] > 0 else bounds.high[axis]
    far_face = bounds.high[axis] if look[axis] > 0 else bounds.low[axis]
    plane = near_face + (far_face - near_face) * depth
    near = abs(plane - position[axis])
    far = abs(far_face - position[axis]) + float(np.linalg.norm(bounds.size)) + 100
    return Camera(view=view, position=cam.position, target=cam.target, up=cam.up, fov=fov,
                  zplanes=(max(1.0, near), far), note=f'cutaway at depth {depth:g} ({"xyz"[axis]} = {plane:.1f})')
