"""Load and validate the panel recipes shared by the CLI and Python API."""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Required, TypedDict

from .camera import Camera, preset
from .layers import Layer, validate_layers
from .leocad import Style
from .mpd import Document
from .validation import boolean, choice, fields, number, text


class Panel(TypedDict, total=False):
    label: str
    parent: str | None
    layers: list[Layer]
    view: str
    camera: dict


class Recipe(TypedDict, total=False):
    source: Required[str]
    panels: Required[list[Panel]]
    section: str
    title: str
    style: dict
    mosaic: bool
    mode: str
    columns: int
    panel_width: int
    legend: list[str]


def load_recipe(value: Mapping | str | Path, style: Style) -> Recipe:
    """Resolve file-relative paths and return a JSON-serializable recipe."""
    base = Path.cwd()
    if isinstance(value, (str, Path)):
        path = Path(value).expanduser().resolve()
        base = path.parent
        value = json.loads(path.read_text(encoding='utf-8'))
    recipe = fields(value, Recipe.__annotations__, required=('source', 'panels'), name='recipe')
    source = Path(text(recipe['source'], 'source')).expanduser()
    source = (base / source).resolve()
    doc = Document.read(source)
    section = recipe.get('section')
    if section is not None:
        text(section, 'section')
    section = doc.model_section(section).name
    overrides = fields(recipe.get('style', {}), Style.__dataclass_fields__, name='style')
    resolved_style = Style.from_dict({**style.to_dict(), **overrides})
    result = Recipe(
        source=str(source), section=section,
        title=text(recipe.get('title', 'Inspection'), 'title', limit=120),
        style=resolved_style.to_dict(),
        mosaic=boolean(recipe.get('mosaic', True), 'mosaic'),
        mode=choice(recipe.get('mode', 'views'), ('views', 'analysis'), 'mode'),
        columns=number(recipe.get('columns', 2), 'columns', integer=True, minimum=1, maximum=4),
        panel_width=number(recipe.get('panel_width', 800), 'panel_width', integer=True, minimum=320, maximum=1600),
        legend=recipe.get('legend', []), panels=[],
    )
    if not isinstance(result['legend'], list) or any(not isinstance(line, str) for line in result['legend']):
        raise ValueError('legend must be a list of strings')
    panels = recipe['panels']
    if not isinstance(panels, list) or not panels:
        raise ValueError('panels must be a nonempty list')
    for index, value in enumerate(panels, 1):
        panel = fields(value, Panel.__annotations__, name=f'panel {index}')
        parent = panel.get('parent')
        if parent is not None:
            parent = doc.parent_name(section, text(parent, f'panel {index} parent'))
        layers = validate_layers(panel.get('layers', []))
        if parent and any(layer['layer'] in ('steps', 'components', 'contacts', 'collisions') for layer in layers):
            raise ValueError(f'Panel {index}: steps and connection overlays require an isolated section; omit parent')
        view = preset(panel.get('view', 'home')).view
        normalized = Panel(
            label=text(panel.get('label', f'Panel {index}'), f'panel {index} label', limit=180),
            parent=parent, layers=layers, view=view,
        )
        if 'camera' in panel:
            if any(layer['layer'] in ('closeup', 'cutaway') for layer in layers):
                raise ValueError(f'Panel {index}: choose camera or closeup/cutaway layers')
            spec = panel['camera']
            if isinstance(spec, dict) and 'fixed' in spec:
                fields(spec, ('fixed',), name='fixed camera')
                normalized['camera'] = {'fixed': preset(spec['fixed']).view}
            else:
                normalized['camera'] = Camera.from_dict(spec).to_dict()
        result['panels'].append(normalized)
    return result
