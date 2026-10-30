"""Connection data for overlays: contacts, connected groups, overlap candidates, axis proposals.

Everything here is evidence for a picture, not a verdict. pyldraw3 finds stud,
receptacle, axle and pin features (LDCad shadow metadata improves coverage a lot);
some interfaces are still missed, so a "floating" group can be a detection gap.

`query_frames` is ported from ldraw-nova's connection_adapter (same author): it
adapts pyldraw3 1.7 query frames for LDCad stud receptacles. Retest it whenever
the pyldraw3 pin changes.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from .mpd import key

LDCAD_SOURCES = None


def _ldcad():
    from ldraw.connection_types import ConnectionSource
    return {ConnectionSource.LDCAD_SHADOW, ConnectionSource.LDCAD_INLINE}


def query_frames(inspection):
    """pyldraw3 1.7: LDCad female spans point inward; strict contact queries expect outward receptacle axes."""
    from ldraw import Matrix
    from ldraw.connection_types import (ConnectionKind, ConnectionRole, ConnectionSource, CylindricalCaps,
                                        CylindricalProfile, SectionShape)
    reverse = Matrix([[1, 0, 0], [0, -1, 0], [0, 0, 1]])
    ldcad = _ldcad()

    def adapt(feature):
        authored = feature.source in ldcad
        profile = feature.profile
        # LDCad models 1-wide brick undersides as closed square cavities that pyldraw 1.7
        # classifies as pin holes; treat them as potential stud receptacles.
        if (authored and feature.role is ConnectionRole.FEMALE and isinstance(profile, CylindricalProfile)
                and not profile.centered and profile.caps in {CylindricalCaps.ONE, CylindricalCaps.B}
                and profile.length >= 4 and profile.sections
                and all(s.shape is SectionShape.SQUARE and abs(s.radius - 6) < 1e-6 and not s.flexible for s in profile.sections)):
            feature = replace(feature, kind=ConnectionKind.STUD_RECEPTACLE, source=ConnectionSource.HEURISTIC,
                              confidence=min(feature.confidence, 0.8),
                              profile=replace(profile, sections=tuple(replace(s, shape=SectionShape.ROUND) for s in profile.sections)))
        if feature.kind is ConnectionKind.STUD_RECEPTACLE and authored:
            feature = replace(feature, frame=feature.frame * reverse)
        return feature

    return replace(inspection, occurrences=tuple(
        replace(item, connections=tuple(adapt(f) for f in item.connections)) for item in inspection.occurrences))


def inspect_section(parts, path, section):
    """pyldraw3 inspection of one section in its own frame."""
    from ldraw import inspect_model, parse_model_result
    path = Path(path)
    result = parse_model_result(path.read_text(encoding='utf-8-sig', errors='replace'), name=path.name, source=path)
    if result.model is None:
        raise ValueError('pyldraw3 could not parse ' + str(path))
    table = {key(s.name): s for s in [result.model, *result.model.submodels.values()]}
    if key(section) not in table:
        raise KeyError(f'Section not found: {section!r}')
    return inspect_model(table[key(section)], parts)


def _vec(v):
    return np.array([float(v.x), float(v.y), float(v.z)])


def contacts(inspection):
    out = []
    for c in query_frames(inspection).connection_contacts():
        out.append(dict(first=c.first_occurrence.index, second=c.second_occurrence.index,
                        point=((_vec(c.first.position) + _vec(c.second.position)) / 2).round(3).tolist(),
                        kinds=[c.first.kind.value, c.second.kind.value], status=c.status.value))
    return out


def groups(inspection, edges):
    parent = list(range(inspection.occurrence_count))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for e in edges:
        a, b = find(e['first']), find(e['second'])
        if a != b:
            parent[a] = b
    members = {}
    for o in inspection.occurrences:
        members.setdefault(find(o.index), []).append(o.index)
    return sorted(members.values(), key=len, reverse=True)


def overlaps(inspection, edges, min_depth=2.0):
    """Occurrence pairs whose world AABBs overlap by more than `min_depth` LDU on every axis
    and that share no detected contact. Coarse: rotated parts have loose boxes."""
    linked = {frozenset((e['first'], e['second'])) for e in edges}
    occ = list(inspection.occurrences)
    lows = np.array([[o.bounds.min.x, o.bounds.min.y, o.bounds.min.z] for o in occ], float)
    highs = np.array([[o.bounds.max.x, o.bounds.max.y, o.bounds.max.z] for o in occ], float)
    out = []
    for i in range(len(occ)):
        depth = np.minimum(highs[i], highs[i + 1:]) - np.maximum(lows[i], lows[i + 1:])
        for j in np.nonzero((depth > min_depth).all(1))[0]:
            j = int(j) + i + 1
            if frozenset((occ[i].index, occ[j].index)) not in linked:
                out.append(dict(first=occ[i].index, second=occ[j].index, depth=depth[j - i - 1].round(2).tolist()))
    return out


def occurrence_info(o):
    a = o.attribution
    return dict(index=o.index, part=o.occurrence.part_code, lines=list(a.source_line_path), path=list(a.reference_path))


def report(parts, path, section, *, shadows=()):
    ins = inspect_section(parts, path, section)
    edges = contacts(ins)
    grp = groups(ins, edges)
    over = overlaps(ins, edges)
    by_index = {o.index: o for o in ins.occurrences}
    status = {}
    for e in edges:
        status[e['status']] = status.get(e['status'], 0) + 1
    return dict(section=section, occurrences=ins.occurrence_count,
                skipped=[dict(part=s.attribution.occurrence.part_code, reason=s.diagnostic.message) for s in ins.skipped_geometry],
                shadow_libraries=[str(s) for s in shadows], contacts=len(edges), contact_status=status,
                groups=[dict(size=len(g), members=[occurrence_info(by_index[i]) for i in g][:20]) for g in grp],
                overlap_candidates=[dict(depth=o['depth'], first=occurrence_info(by_index[o['first']]),
                                         second=occurrence_info(by_index[o['second']])) for o in over[:200]],
                limits=['Detected contacts are evidence, not proof of clutch or fit.',
                        'Technic pin/axle mating and some special parts are not paired; a separate group may be a detection gap.',
                        'Overlap candidates come from axis-aligned boxes and need a visual check.'])


def propose_axes(parts, path, section, *, tolerance=0.5):
    """Lines along which cylindrical features of two or more parts coincide (candidate revolute axes)."""
    from ldraw.connection_types import ConnectionKind
    kinds = {ConnectionKind.AXLE, ConnectionKind.AXLE_HOLE, ConnectionKind.PIN, ConnectionKind.PIN_HOLE}
    ins = inspect_section(parts, path, section)
    feats = []
    for o in ins.occurrences:
        for f in o.connections:
            if f.kind in kinds:
                m = np.array([[float(v) for v in row] for row in f.frame.rows]) if hasattr(f.frame, 'rows') else np.array(f.frame, float)
                feats.append((o.index, o.occurrence.part_code, f.kind.value, _vec(f.position), m @ np.array([0.0, 1.0, 0.0])))
    lines = []
    for idx, part, kind, p, d in feats:
        d = d / np.linalg.norm(d)
        for line in lines:
            if abs(float(d @ line['direction'])) > 0.999:
                off = p - line['point']
                if np.linalg.norm(off - (off @ line['direction']) * line['direction']) < tolerance:
                    line['features'].append((idx, part, kind, p))
                    break
        else:
            lines.append(dict(point=p, direction=d, features=[(idx, part, kind, p)]))
    out = []
    for line in lines:
        occ = {f[0] for f in line['features']}
        if len(occ) < 2:
            continue
        d = line['direction']
        d = d if d[np.argmax(abs(d))] > 0 else -d
        pts = np.array([f[3] for f in line['features']])
        t = (pts - line['point']) @ d
        centre = line['point'] + d * (t.min() + t.max()) / 2
        out.append(dict(point=centre.round(3).tolist(), direction=d.round(4).tolist(), parts=len(occ),
                        features=[dict(occurrence=f[0], part=f[1], kind=f[2]) for f in line['features']]))
    out.sort(key=lambda a: -a['parts'])
    return dict(section=section, frame='section coordinates; LDraw -Y is up', candidates=out[:20],
                note='Coaxial features only show a shared line; they do not prove the joint turns. Pass the chosen axis explicitly.')
