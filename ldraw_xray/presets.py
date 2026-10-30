"""Starting-point recipes for common inspections. Agents edit the written recipe.json and re-run it."""
from __future__ import annotations

from .mpd import Document


def _parent(source, section):
    """First block placing the section, unless it holds nothing else (then a parent view adds nothing)."""
    doc = Document.read(source)
    for name, hits in doc.parents_of(section).items():
        if len(doc.block(name).placements()) > len(hits):
            return name
    return None


def overview(source, section, *, steps=(), parent=None, **_):
    """Where it sits, what it looks like, how it is built."""
    parent = parent or _parent(source, section)
    panels = []
    if parent:
        panels.append(dict(label=f'In {parent}: the section highlighted, the rest ghosted', context='parent',
                           layers=['highlight', 'ghost'], view='home'))
    panels.append(dict(label='Isolated, home view', layers=[], view='home'))
    for s in steps:
        panels.append(dict(label=f'Source step {s}: new parts edged magenta', layers=[f'steps:first={s};last={s}'], view='home'))
    if len(panels) < 4:
        panels.append(dict(label='Isolated, front view', layers=[], view='front'))
    return dict(title=f'{section}: overview', source=str(source), section=section, parent=parent, panels=panels)


def snot(source, section, *, steps=(), parent=None, **_):
    """Stud directions in non-LEGO colours, plus where the parent puts the section."""
    parent = parent or _parent(source, section)
    panels = []
    if parent:
        panels.append(dict(label=f'In {parent}: the section highlighted', context='parent', layers=['highlight'], view='home'))
    panels += [dict(label='Stud-direction map, home view (section frame)', layers=['stud_map'], view='home'),
               dict(label='Stud-direction map, front view (section frame)', layers=['stud_map'], view='front')]
    for s in steps:
        panels.append(dict(label=f'Source step {s}: new parts edged magenta', layers=[f'steps:first={s};last={s}'], view='home'))
    return dict(title=f'{section}: stud directions', source=str(source), section=section, parent=parent, panels=panels)


def xray(source, section, *, sel, colour='47', highlight=None, **_):
    """See through a shell (`sel`) to what it hides; optionally edge the hidden parts magenta."""
    layers = [f'xray:sel={sel};colour={colour}'] + ([f'highlight:sel={highlight}'] if highlight else [])
    return dict(title=f'{section}: x-ray of {sel}', source=str(source), section=section, panels=[
        dict(label='Isolated, home view (as built)', layers=[], view='home'),
        dict(label=f'X-ray: {sel} see-through', layers=layers, view='home'),
        dict(label=f'X-ray: {sel} see-through, front view', layers=layers, view='front'),
        dict(label=f'X-ray: {sel} see-through, top view', layers=layers, view='top')])


def pivot(source, section, *, point, direction, moving, hardware=None, angles=(0, 45, 90), parent=None, **_):
    """Axis rod, joint hardware edged magenta, and a pose sweep from one fixed camera."""
    parent = parent or _parent(source, section)
    p, d = ','.join(f'{v:g}' for v in point), ','.join(f'{v:g}' for v in direction)
    axis = f'axis:point={p};direction={d}'
    marks = [axis] + ([f'highlight:sel={hardware}'] if hardware else [])
    panels = [dict(label='Axis rod (green) and joint hardware (magenta edges)', layers=marks, view='home')]
    if parent:
        panels.append(dict(label=f'In {parent}: axis rod through the highlighted section', context='parent',
                           layers=['highlight', 'ghost', axis], view='home'))
    for a in angles:
        panels.append(dict(label=f'Pose {a:g} degrees about the axis (moving: {moving})',
                           layers=[f'pose:sel={moving};point={p};direction={d};angle={a:g}', *marks],
                           camera=dict(fixed='home')))
    return dict(title=f'{section}: pivot', source=str(source), section=section, parent=parent, panels=panels,
                columns=3 if len(panels) > 4 else 2, panel_width=640 if len(panels) > 4 else 800)


def cutaway(source, section, *, view='front', depths=(0.35, 0.5, 0.65), **_):
    """Slice the section open with the camera's near plane at several depths."""
    panels = [dict(label=f'Isolated, {view} view (uncut)', layers=[], view=view)]
    for d in depths:
        panels.append(dict(label=f'Cut at depth {d:g} from the {view}', layers=[f'cutaway:view={view};depth={d:g}']))
    return dict(title=f'{section}: cutaway from the {view}', source=str(source), section=section, panels=panels)


PRESETS = dict(overview=overview, snot=snot, xray=xray, pivot=pivot, cutaway=cutaway)
