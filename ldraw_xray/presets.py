"""Small recipe builders for common inspection tasks."""
from __future__ import annotations

from pathlib import Path

from .mpd import Document, step_map
from .validation import number, vector


def _subject(source, section):
    source = Path(source).expanduser().resolve()
    doc = Document.read(source)
    return source, doc, doc.model_section(section).name


def _parent(doc, section, parent):
    return doc.parent_name(section, parent, useful=True, required=False)


def _step_panels(doc, section, steps):
    available = step_map(doc.block(section).placements())
    if steps == 'all':
        requested = list(available)
    else:
        requested = sorted(set(steps))
        for step in requested:
            number(step, 'step', integer=True, positive=True)
        requested = [step for step in requested if step in available]
    if steps and not requested:
        raise ValueError(f'No requested nonempty source steps; steps with parts: {list(available)}')
    return [dict(label=f'Source step {step}: new parts edged magenta',
                 layers=[dict(layer='steps', numbers=[step])], view='home') for step in requested]


def overview(source, section=None, *, steps=(), parent=None):
    """Where it sits, what it looks like, and how it is built."""
    source, doc, section = _subject(source, section)
    parent = _parent(doc, section, parent)
    panels = []
    if parent:
        panels.append(dict(label=f'In {parent}: highlighted section, ghosted surroundings', parent=parent,
                           layers=[dict(layer='highlight'), dict(layer='ghost')], view='home'))
    panels.append(dict(label='Isolated, home view', view='home'))
    panels.extend(_step_panels(doc, section, steps))
    if len(panels) < 4:
        panels.append(dict(label='Isolated, front view', view='front'))
    return dict(title=f'{section}: overview', source=str(source), section=section, panels=panels)


def stud_map(source, section=None, *, steps=(), parent=None):
    """Stud directions in section coordinates, plus the section in its parent."""
    source, doc, section = _subject(source, section)
    parent = _parent(doc, section, parent)
    panels = []
    if parent:
        panels.append(dict(label=f'In {parent}: highlighted section', parent=parent,
                           layers=[dict(layer='highlight')], view='home'))
    for view in ('home', 'front'):
        panels.append(dict(label=f'Stud directions, {view} view (section coordinates)',
                           layers=[dict(layer='stud_map')], view=view))
    panels.extend(_step_panels(doc, section, steps))
    return dict(title=f'{section}: stud directions', source=str(source), section=section, panels=panels)


def xray(source, section=None, *, select, colour=47, highlight=None):
    """The original model followed by three views through the selected shell."""
    source, _, section = _subject(source, section)
    layers = [dict(layer='xray', select=select, colour=colour)]
    if highlight is not None:
        layers.append(dict(layer='highlight', select=highlight))
    panels = [dict(label='As built, home view', view='home')]
    panels.extend(dict(label=f'X-ray, {view} view', layers=layers, view=view) for view in ('home', 'front', 'top'))
    return dict(title=f'{section}: x-ray', source=str(source), section=section, panels=panels)


def pivot(source, section=None, *, point, direction, moving, hardware=None, angles=(0, 45, 90), parent=None):
    """Axis marker, optional parent context, and a pose sweep with one fixed camera."""
    source, doc, section = _subject(source, section)
    parent = _parent(doc, section, parent)
    point = list(vector(point, 'point'))
    direction = list(vector(direction, 'direction', nonzero=True))
    if not isinstance(angles, (list, tuple)) or not angles:
        raise ValueError('angles must be a nonempty list')
    axis = dict(layer='axis', point=point, direction=direction)
    marks = [axis]
    if hardware is not None:
        marks.append(dict(layer='highlight', select=hardware))
    panels = [dict(label='Axis marker and joint hardware', layers=marks, view='home')]
    if parent:
        panels.append(dict(label=f'In {parent}: axis through highlighted section', parent=parent,
                           layers=[dict(layer='highlight'), dict(layer='ghost'), axis], view='home'))
    for angle in angles:
        number(angle, 'angle')
        pose = dict(layer='pose', select=moving, point=point, direction=direction, angle=angle)
        panels.append(dict(label=f'Pose {angle:g} degrees', layers=[pose, *marks], camera=dict(fixed='home')))
    return dict(title=f'{section}: pivot', source=str(source), section=section, panels=panels,
                columns=3 if len(panels) > 4 else 2, panel_width=640 if len(panels) > 4 else 800)


def cutaway(source, section=None, *, view='front', depths=(0.35, 0.5, 0.65)):
    """Uncut view followed by cuts at each requested depth."""
    source, _, section = _subject(source, section)
    if not isinstance(depths, (list, tuple)) or not depths:
        raise ValueError('depths must be a nonempty list')
    panels = [dict(label=f'Uncut, {view} view', view=view)]
    for depth in depths:
        number(depth, 'depth', minimum=0, maximum=1)
        panels.append(dict(label=f'Cut at depth {depth:g} from the {view}',
                           layers=[dict(layer='cutaway', view=view, depth=depth)], view=view))
    return dict(title=f'{section}: cutaway', source=str(source), section=section, panels=panels)
