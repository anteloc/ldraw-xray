"""Small geometry helpers that renders need: rotations, stud directions, bounds."""
from __future__ import annotations

import math

import numpy as np

STUD_UP = np.array([0.0, -1.0, 0.0])  # LDraw -Y is up; studs point along local -Y


def unit(v):
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if n < 1e-12:
        raise ValueError('Direction must be non-zero')
    return v / n


def rotation(axis, degrees):
    """Right-handed rotation about `axis` (Rodrigues)."""
    k = unit(axis)
    a = math.radians(degrees)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(a) * K + (1 - math.cos(a)) * (K @ K)


def basis_y(direction):
    """Orthonormal matrix whose local +Y maps to `direction` (for rods along local Y)."""
    y = unit(direction)
    helper = np.array([1.0, 0, 0]) if abs(y[0]) < 0.9 else np.array([0, 0, 1.0])
    x = unit(np.cross(helper, y))
    z = np.cross(x, y)
    return np.column_stack([x, y, z])


def stud_bucket(matrix, tolerance=0.98):
    """Where a placement's studs point: up/down/+x/-x/+z/-z, or 'angled'."""
    d = np.asarray(matrix) @ STUD_UP
    ax = int(np.argmax(abs(d)))
    if abs(d[ax]) < tolerance:
        return 'angled'
    return {(1, -1): 'up', (1, 1): 'down', (0, 1): '+x', (0, -1): '-x', (2, 1): '+z', (2, -1): '-z'}[(ax, int(np.sign(d[ax])))]


def map_axis(point, direction, placement_pos, placement_matrix):
    """Map an axis from a child frame into its parent through one placement."""
    m = np.asarray(placement_matrix, dtype=float)
    return m @ np.asarray(point, dtype=float) + np.asarray(placement_pos, dtype=float), unit(m @ np.asarray(direction, dtype=float))


class Bounds:
    def __init__(self, low, high, points=None):
        self.low, self.high = np.asarray(low, float), np.asarray(high, float)
        self.points = points          # optional (N, 3) corner cloud for tight camera fits

    @property
    def centre(self):
        return (self.low + self.high) / 2

    @property
    def size(self):
        return self.high - self.low

    def to_dict(self):
        return dict(min=[round(float(v), 3) for v in self.low], max=[round(float(v), 3) for v in self.high])


_LOCAL = {}


def _local(parts, ref):
    code = ref.replace('\\', '/')
    code = code[:-4] if code.casefold().endswith('.dat') else code
    try:
        b = parts.bounding_box(code)
    except Exception:  # unknown or geometry-free parts
        return None
    lo, hi = b.min, b.max
    return np.array([lo.x, lo.y, lo.z]), np.array([hi.x, hi.y, hi.z])


def leaf_bounds(parts, placements):
    """World AABB of leaf placements from each part's local bounds (8 transformed corners).

    Returns (Bounds or None, skipped refs). Parts unknown to the library (for
    example embedded DAT blocks) are skipped and reported.
    """
    def local(ref):
        k = (id(parts), ref.casefold())
        if k not in _LOCAL:
            _LOCAL[k] = _local(parts, ref)
        return _LOCAL[k]

    points, skipped = [], set()
    for p in placements:
        lb = local(p.ref)
        if lb is None:
            skipped.add(p.ref)
            continue
        lo, hi = lb
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        points.append(corners @ np.asarray(p.matrix).T + p.pos)
    if not points:
        return None, sorted(skipped)
    allp = np.vstack(points)
    return Bounds(allp.min(0), allp.max(0), np.unique(allp.round(1), axis=0)), sorted(skipped)
