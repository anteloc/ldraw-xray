"""Composable inspection layers applied to a synthetic copy of a model.

A Scene names a source file, the inspected section and optionally a parent to
show it in. Layers edit two placement lists: the section's and, in a parent
context, the parent's. Layers that change content (xray, recolour, stud_map,
pose, axis) edit the section, so a parent render shows the change too. Layers
that drive LeoCAD's step highlighting (highlight, ghost) edit the rendered
block: the section when isolated, the parent in context.

Composition rules (LeoCAD behaviour, measured):
- highlight draws the selected parts' edges magenta; their colours stay;
- ghost fades everything outside the highlight and replaces its colours, so
  out-of-band colours only survive on highlighted parts;
- steps renders source steps and cannot be combined with highlight or ghost.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import camera as cam
from .geometry import Bounds, basis_y, leaf_bounds, map_axis, rotation, stud_bucket, unit
from .mpd import Block, Document, Placement, emit, key, step_map
from .palette import AXIS_CODE, DIRECTION_CODES, legend, resolve
from .select import select

SYNTHETIC = '0 // ldraw-xray synthetic inspection copy: recoloured/moved/marked for rendering, not a valid model'


@dataclass(frozen=True)
class Scene:
    source: Path
    section: str
    context: str = 'isolate'          # 'isolate' or 'parent'
    parent: str | None = None         # parent block; default: first block that places the section

    def to_dict(self):
        return dict(source=str(self.source), section=self.section, context=self.context, parent=self.parent)


@dataclass
class Plan:
    """What the renderer needs after the layers ran."""

    doc: Document
    submodel: str
    steps: list[tuple[int, int]] | None   # (source step, rendered step) pairs for step renders
    final_step: int | None                # rendered step holding the highlight, if any
    highlight: bool
    fade: bool
    camera: cam.Camera | None
    legend: list[dict]
    records: list[dict]
    notes: list[str]
    parent_placements: list[str]
    bounds: Bounds | None = None


class Build:
    def __init__(self, scene: Scene, parts=None):
        self.scene = scene
        self.parts = parts                 # pyldraw3 Parts, needed for bounds-based layers
        self.doc = Document.read(scene.source)
        self.section = self.doc.block(scene.section)
        if self.section.is_part:
            raise ValueError(f'{scene.section!r} is a part definition, not a model section')
        self.parent = None
        if scene.context == 'parent':
            parents = self.doc.parents_of(self.section.name)
            name = scene.parent or next(iter(parents), None)
            if not name:
                raise ValueError(f'No block places {self.section.name!r}; use context isolate')
            self.parent = self.doc.block(name)
        elif scene.context != 'isolate':
            raise ValueError("context must be 'isolate' or 'parent'")
        self.items = {'section': self.section.placements()}
        if self.parent:
            self.items['parent'] = self.parent.placements()
        self.keep_steps = None
        self.fade = False
        self.cutaway_request = None
        self.camera = None
        self.aspect = 4 / 3
        self.codes = set()
        self.records = []
        self.notes = []
        self.markers = []
        self.axis_requests = []

    # -- helpers -------------------------------------------------------------
    def scope(self, scope):
        scope = scope or ('parent' if self.parent else 'section')
        if scope == 'parent' and not self.parent:
            raise ValueError("scope 'parent' needs context 'parent'")
        if scope not in self.items:
            raise ValueError(f'Unknown scope {scope!r}')
        return scope

    def chosen(self, scope, sel, default=None):
        spec = sel if sel is not None else default
        if spec is None:
            raise ValueError('This layer needs a selection (sel=...)')
        idx = select(spec, self.items[scope], section=self.section.name)
        if not idx:
            self.notes.append(f'Selection {spec!r} matched nothing in {scope}')
        return idx, spec

    def flatten_selected(self, scope, idx):
        """Replace selected child-model placements by their leaves (so explicit colours inside can change)."""
        out, chosen = [], set()
        for i, p in enumerate(self.items[scope]):
            leaves = list(self.doc.flatten(p)) if i in idx else [p]
            if i in idx:
                chosen.update(range(len(out), len(out) + len(leaves)))
            out.extend(leaves)
        self.items[scope] = out
        return chosen

    def bounds(self, scope, idx=None):
        if self.parts is None:
            raise ValueError('This layer needs the LDraw library index (bounds)')
        items = self.items[scope]
        leaves = [l for i, p in enumerate(items) if idx is None or i in idx for l in self.doc.flatten(p)]
        b, skipped = leaf_bounds(self.parts, leaves)
        skipped = [s for s in skipped if not s.casefold().startswith('xray-')]
        if skipped and not any(n.startswith('Bounds skip') for n in self.notes):
            self.notes.append(f'Bounds skip parts unknown to the library: {", ".join(skipped[:5])}')
        if b is None:
            raise ValueError('No measurable geometry for bounds')
        return b

    def record(self, layer, **info):
        self.records.append(dict(layer=layer, **{k: v for k, v in info.items() if v is not None}))

    # -- layers --------------------------------------------------------------
    def highlight(self, sel=None, scope=None):
        scope = self.scope(scope)
        default = 'section' if scope == 'parent' else None
        idx, spec = self.chosen(scope, sel, default)
        self.items[scope] = [p.moved(final=True) if i in idx else p for i, p in enumerate(self.items[scope])]
        self.record('highlight', sel=spec, scope=scope, count=len(idx))

    def ghost(self):
        self.fade = True
        self.record('ghost')

    def steps(self, first=None, last=None):
        if self.parent:
            raise ValueError('steps renders the isolated section; use context isolate')
        self.keep_steps = (first, last)
        self.record('steps', first=first, last=last)

    def recolour(self, sel=None, colour='group:A', scope='section', layer='recolour'):
        scope = self.scope(scope)
        code = resolve(colour)
        idx, spec = self.chosen(scope, sel)
        idx = self.flatten_selected(scope, idx)
        self.items[scope] = [p.moved(colour=str(code)) if i in idx else p for i, p in enumerate(self.items[scope])]
        self.codes.add(code)
        self.record(layer, sel=spec, scope=scope, colour=code, count=len(idx))

    def xray(self, sel=None, colour=47, scope='section'):
        self.recolour(sel, colour, scope, layer='xray')

    def stud_map(self, sel='all', scope='section'):
        scope = self.scope(scope)
        idx, spec = self.chosen(scope, sel)
        idx = self.flatten_selected(scope, idx)
        counts = {}
        items = []
        for i, p in enumerate(self.items[scope]):
            if i in idx:
                b = stud_bucket(p.matrix)
                counts[b] = counts.get(b, 0) + 1
                p = p.moved(colour=str(DIRECTION_CODES[b]))
            items.append(p)
        self.items[scope] = items
        self.codes.update(DIRECTION_CODES.values())
        self.record('stud_map', sel=spec, scope=scope, frame=f'{scope} coordinates; LDraw -Y is up',
                    counts=counts, total=sum(counts.values()))

    def pose(self, sel=None, point=(0, 0, 0), direction=(0, 0, 1), angle=0.0, scope='section'):
        scope = self.scope(scope)
        idx, spec = self.chosen(scope, sel)
        c, R = np.asarray(point, float), rotation(direction, float(angle))
        self.items[scope] = [p.moved(pos=R @ (p.pos - c) + c, matrix=R @ p.matrix) if i in idx else p
                             for i, p in enumerate(self.items[scope])]
        self.record('pose', sel=spec, scope=scope, point=list(map(float, point)),
                    direction=list(map(float, unit(direction))), angle=float(angle), count=len(idx))

    def axis(self, point=(0, 0, 0), direction=(0, 0, 1), length=None, radius=None):
        """Neon-green rod along an axis given in section coordinates (drawn in the section)."""
        self.axis_requests.append((tuple(map(float, point)), tuple(map(float, unit(direction))), length, radius))
        self.codes.add(AXIS_CODE)

    def closeup(self, sel='section', scope=None, view='home', margin=1.25):
        scope = self.scope(scope)
        idx, spec = self.chosen(scope, sel)
        self.camera = cam.fitted(self.bounds(scope, idx), view, margin=margin, note=f'close-up on {spec}')
        self.record('closeup', sel=spec, scope=scope, view=view)

    def cutaway(self, view='front', depth=0.5):
        self.cutaway_request = (view, float(depth))
        self.record('cutaway', view=view, depth=float(depth))

    # -- connection overlays (pyldraw3; isolated section, source geometry) ----
    def _connections(self):
        if self.parent:
            raise ValueError('Connection overlays render the isolated section; use context isolate')
        if self.parts is None:
            raise ValueError('Connection overlays need the LDraw library index')
        if getattr(self, '_conn', None) is None:
            from . import connections
            ins = connections.inspect_section(self.parts, self.scene.source, self.section.name)
            self._conn = (ins, connections.contacts(ins))
            if ins.skipped_geometry:
                self.notes.append('pyldraw3 skipped: ' + ', '.join(sorted({s.attribution.occurrence.part_code
                                                                            for s in ins.skipped_geometry}))[:200])
        return self._conn

    def _leaf_index(self):
        """Flatten the whole section; map pyldraw3 occurrence line paths to leaf indices."""
        self.items['section'] = [l for p in self.items['section'] for l in self.doc.flatten(p)]
        return {tuple(l.origin): i for i, l in enumerate(self.items['section'])}

    def _recolour_occurrences(self, occurrences, code):
        ins, _ = self._connections()
        index = self._leaf_index()
        paths = {o.index: tuple(o.attribution.source_line_path) for o in ins.occurrences}
        hit = {index[paths[i]] for i in occurrences if paths.get(i) in index}
        self.items['section'] = [p.moved(colour=str(code)) if i in hit else p for i, p in enumerate(self.items['section'])]
        self.codes.add(code)
        return len(hit)

    def components(self):
        """Recolour every connected group except the largest; small groups are floating or undetected joints."""
        from .connections import groups
        from .palette import GROUP_CODES
        ins, edges = self._connections()
        grp = groups(ins, edges)
        sizes = []
        for n, members in enumerate(grp[1:]):
            code = GROUP_CODES[n % len(GROUP_CODES)]
            self._recolour_occurrences(members, code)
            sizes.append(dict(colour=code, size=len(members)))
        self.record('components', groups=len(grp), largest=len(grp[0]) if grp else 0, others=sizes[:24],
                    caveat='a separate group can be a connection-detection gap, not a loose part')

    def collisions(self, min_depth=2.0):
        from .connections import overlaps
        from .palette import BY_NAME
        ins, edges = self._connections()
        pairs = overlaps(ins, edges, float(min_depth))
        members = {i for p in pairs for i in (p['first'], p['second'])}
        n = self._recolour_occurrences(members, BY_NAME['Xray_Collision'].code)
        self.record('collisions', pairs=len(pairs), parts=n, min_depth=float(min_depth),
                    caveat='axis-aligned box overlaps without a detected contact; candidates only')

    def contacts(self, radius=2.5):
        from .palette import BY_NAME
        _, edges = self._connections()
        name = 'xray-contact-marker.dat'
        if key(name) not in self.doc.blocks:
            octants = [(sx, sy, sz) for sx in (1, -1) for sy in (1, -1) for sz in (1, -1)]
            self.doc.add_block(name, ['0 ldraw-xray contact marker (synthetic, not a LEGO part)', f'0 Name: {name}',
                                      '0 !LDRAW_ORG Unofficial_Part', '0 BFC NOCERTIFY',
                                      *(f'1 16 0 0 0 {sx} 0 0 0 {sy} 0 0 0 {sz} 1-8sphe.dat' for sx, sy, sz in octants)])
        confirmed, heuristic = BY_NAME['Xray_Contact_Confirmed'].code, BY_NAME['Xray_Contact_Heuristic'].code
        r = float(radius)
        scale = np.diag([r, r, r])
        for e in edges:
            code = confirmed if e['status'] == 'confirmed' else heuristic
            self.items['section'].append(Placement(str(code), np.array(e['point']), scale, name, None, 1, (None,)))
            self.codes.add(code)
        counts = {}
        for e in edges:
            counts[e['status']] = counts.get(e['status'], 0) + 1
        self.record('contacts', total=len(edges), status=counts, radius=r,
                    caveat='detected connector pairs; Technic pin/axle mating is not detected')

    # -- finish --------------------------------------------------------------
    def _add_axes(self):
        rendered = 'parent' if self.parent else 'section'
        for n, (point, direction, length, radius) in enumerate(self.axis_requests):
            if length is None or radius is None:
                extent = float(np.max(self.bounds('section').size)) if self.parts is not None else 200.0
                length = length or round(extent * 1.3, 1)
                if radius is None:
                    ref_extent = float(np.max(self.bounds(rendered).size)) if self.parts is not None else extent
                    radius = round(max(1.5, ref_extent * 0.006), 2)
            name = f'xray-axis-{n}.dat'
            half = length / 2
            self.doc.add_block(name, ['0 ldraw-xray axis marker (synthetic, not a LEGO part)', f'0 Name: {name}',
                                      '0 !LDRAW_ORG Unofficial_Part', '0 BFC NOCERTIFY',
                                      f'1 16 0 {-half:g} 0 {radius:g} 0 0 0 {length:g} 0 0 0 {radius:g} 4-4cyli.dat',
                                      f'1 16 0 {-half:g} 0 {radius:g} 0 0 0 1 0 0 0 {radius:g} 4-4disc.dat',
                                      f'1 16 0 {half:g} 0 {radius:g} 0 0 0 1 0 0 0 {radius:g} 4-4disc.dat'])
            rod = Placement(str(AXIS_CODE), np.asarray(point), basis_y(direction), name, None, 1, (None,),
                            final=self.fade and not self.parent)
            self.items['section'].append(rod)
            info = dict(point=list(point), direction=list(direction), length=length, radius=radius, frame='section')
            if self.parent:
                info['in_parent'] = [dict(zip(('point', 'direction'), (list(map(lambda v: round(float(v), 3), a)) for a in
                                                                       map_axis(point, direction, p.pos, p.matrix))))
                                     for p in self.items['parent'] if key(p.ref) == key(self.section.name)]
            self.record('axis', **info)

    def plan(self) -> Plan:
        self._add_axes()
        rendered = 'parent' if self.parent else 'section'
        if self.parent and any(p.final for p in self.items['section']):
            raise ValueError("In a parent context, highlight parent placements (scope parent, e.g. sel=section)")
        if self.fade and not any(p.final for p in self.items[rendered]):
            raise ValueError('ghost needs a highlight: something must stay solid')
        header = [*self.section.header(), SYNTHETIC]
        steps = final_step = None
        keep = self.keep_steps is not None
        self.section.lines = emit(header, self.items['section'], keep_steps=keep)
        if keep:
            mapping = step_map(self.items['section'])
            first, last = self.keep_steps
            wanted = [s for s in mapping if (first is None or s >= first) and (last is None or s <= last)]
            if not wanted:
                raise ValueError(f'No non-empty source steps in {first}..{last}; steps with parts: {sorted(mapping)}')
            steps = [(s, mapping[s]) for s in wanted]
        if self.parent:
            self.parent.lines = emit([*self.parent.header(), SYNTHETIC], self.items['parent'], keep_steps=False)
        block = self.parent or self.section
        finals = [p for p in self.items[rendered] if p.final]
        if finals:
            final_step = 2 if any(not p.final for p in self.items[rendered]) else 1
        camera = self.camera
        if self.cutaway_request:
            view, depth = self.cutaway_request
            camera = cam.cutaway(self.bounds(rendered), view, depth, aspect=self.aspect)
        parent_placements = [p.text() for p in Block(block.name, block.lines).placements()
                             if self.parent and key(p.ref) == key(self.section.name)]
        bounds = None
        if self.parts is not None:
            try:
                bounds = self.bounds(rendered)
            except ValueError as e:
                self.notes.append(f'No bounds for framing ({e}); LeoCAD viewpoints used')
            if bounds is not None and not self.parent:
                for r in (r for r in self.records if r['layer'] == 'axis'):
                    p, d = np.array(r['point']), np.array(r['direction'])
                    ends = np.array([p - d * r['length'] / 2, p + d * r['length'] / 2])
                    bounds = Bounds(np.minimum(bounds.low, ends.min(0)), np.maximum(bounds.high, ends.max(0)))
        return Plan(self.doc, block.name, steps, final_step, highlight=bool(finals) or keep, fade=self.fade,
                    camera=camera, legend=legend(self.codes), records=self.records, notes=self.notes,
                    parent_placements=parent_placements, bounds=bounds)


LAYERS = {
    'highlight': ('sel', 'scope'),
    'ghost': (),
    'steps': ('first', 'last'),
    'xray': ('sel', 'colour', 'scope'),
    'recolour': ('sel', 'colour', 'scope'),
    'stud_map': ('sel', 'scope'),
    'pose': ('sel', 'point', 'direction', 'angle', 'scope'),
    'axis': ('point', 'direction', 'length', 'radius'),
    'closeup': ('sel', 'scope', 'view', 'margin'),
    'cutaway': ('view', 'depth'),
    'contacts': ('radius',),
    'components': (),
    'collisions': ('min_depth',),
}
VECTORS = {'point', 'direction'}
NUMBERS = {'first', 'last', 'angle', 'length', 'radius', 'depth', 'margin', 'min_depth'}


def parse_layer(text):
    """`name` or `name:key=value;key=value`, e.g. `xray:sel=colour:15;colour=Xray_Glass`.

    Vectors are comma-separated (`point=0,-18,0`).
    """
    if isinstance(text, dict):
        spec = dict(text)
        name = spec.pop('layer')
    else:
        name, _, rest = str(text).partition(':')
        spec = {}
        for part in filter(None, (p.strip() for p in rest.split(';'))):
            k, eq, v = part.partition('=')
            if not eq:
                raise ValueError(f'Layer option {part!r} must be key=value')
            spec[k.strip()] = v.strip()
    name = name.strip()
    if name not in LAYERS:
        raise ValueError(f'Unknown layer {name!r}; available: {", ".join(LAYERS)}')
    unknown = set(spec) - set(LAYERS[name])
    if unknown:
        raise ValueError(f'Layer {name!r} takes {", ".join(LAYERS[name]) or "no options"}; got {", ".join(sorted(unknown))}')
    for k, v in list(spec.items()):
        if k in VECTORS and isinstance(v, str):
            spec[k] = tuple(float(x) for x in v.split(','))
        elif k in NUMBERS and isinstance(v, str):
            spec[k] = float(v) if k not in ('first', 'last') else int(v)
    return dict(layer=name, **spec)


def apply(build: Build, layers):
    for raw in layers:
        spec = parse_layer(raw)
        name = spec.pop('layer')
        getattr(build, name)(**spec)
    return build
