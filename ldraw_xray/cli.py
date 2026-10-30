"""Conventional commands in, one JSON result out; help remains ordinary text."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .camera import VIEWS
from .config import XrayConfig, discover
from .mpd import Document
from .select import numbers


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, allow_abbrev=False, **kwargs)

    def error(self, message):
        raise ValueError(f'{self.prog}: {message}; see {self.prog} --help')


def _configuration(parser):
    # Suppressed defaults let flags before the command survive leaf parsing.
    parser.add_argument('--library', default=argparse.SUPPRESS, help='LDraw library (LDRAW_DIR, then LDRAWDIR)')
    shadow = parser.add_mutually_exclusive_group()
    shadow.add_argument('--shadow', action='append', default=argparse.SUPPRESS,
                        help='LDCad shadow directory, ZIP or CSL; repeat to replace LDRAW_SHADOW')
    shadow.add_argument('--no-shadow', action='store_true', default=argparse.SUPPRESS, help='Ignore LDRAW_SHADOW')
    parser.add_argument('--leocad', default=argparse.SUPPRESS, help='LeoCAD executable (LEOCAD, PATH, macOS app)')
    parser.add_argument('--cache-dir', default=argparse.SUPPRESS, help='Index cache (LDRAW_XRAY_CACHE or user cache)')


def _model(parser, *, parent=False):
    parser.add_argument('file', help='LDraw .mpd or .ldr file')
    parser.add_argument('--section', help='Model section (default: root model)')
    if parent:
        parser.add_argument('--parent', nargs='?', const=True, metavar='NAME',
                            help='Show in NAME, or the unique parent when NAME is omitted')


def _output(parser, *, board=False):
    parser.add_argument('-o', '--output', required=True, help='Output directory')
    parser.add_argument('--force', action='store_true', help='Replace generated files; keep unrelated files')
    parser.add_argument('--keep-intermediates', action='store_true', help='Keep transparent PNGs and synthetic models')
    if board:
        parser.add_argument('--no-mosaic', action='store_true', help='Render panels without a mosaic')


def _step_numbers(value):
    if value == 'all':
        return value
    return sorted(numbers(value))


def _steps(parser):
    parser.add_argument('--steps', nargs='?', const='all', type=_step_numbers, default=argparse.SUPPRESS,
                        metavar='NUMBERS', help='Source steps, e.g. 3,7-9; omit NUMBERS for all nonempty steps')


def parser():
    root = Parser(prog='ldraw-xray', description='Render and inspect LDraw models with LeoCAD.')
    _configuration(root)
    commands = root.add_subparsers(dest='command', required=True)

    def command(name, help):
        child = commands.add_parser(name, help=help, description=help)
        _configuration(child)
        return child

    command('doctor', 'Show available dependencies and setup problems')
    palette = command('palette', 'List inspection colours')
    palette.add_argument('--check', action='store_true', help='Measure colours against the LDraw library palette')
    command('sections', 'List model sections, source steps, and parents').add_argument('file')

    render = command('render', 'Render a model or section with common inspection effects')
    _model(render, parent=True)
    _output(render)
    render.add_argument('--view', action='append', choices=VIEWS, help='View to render; repeat for more (default: home)')
    colours = render.add_mutually_exclusive_group()
    colours.add_argument('--xray', metavar='SELECTOR', help='Make selected parts transparent, e.g. colour:15')
    colours.add_argument('--stud-map', action='store_true', help='Colour parts by stud direction')
    render.add_argument('--highlight', metavar='SELECTOR', help='Give selected parts magenta edges, e.g. step:3')
    render.add_argument('--ghost', action='store_true', help='Fade everything outside --highlight')
    _steps(render)

    board = commands.add_parser('board', help='Make an inspection board or replay a recipe')
    tasks = board.add_subparsers(dest='task', required=True)
    descriptions = {
        'overview': 'Parent context, isolated views, and optional source steps',
        'stud-map': 'Stud directions and parent context',
        'xray': 'As-built and transparent-shell views',
        'pivot': 'Axis marker and poses with one fixed camera',
        'cutaway': 'An uncut view and slices at selected depths',
        'run': 'Run a saved or edited JSON recipe',
    }
    for name, description in descriptions.items():
        task = tasks.add_parser(name, help=description, description=description)
        _configuration(task)
        _output(task, board=True)
        if name == 'run':
            task.add_argument('recipe', help='JSON recipe file')
            continue
        _model(task, parent=name in ('overview', 'stud-map', 'pivot'))
        if name in ('overview', 'stud-map'):
            _steps(task)
        elif name == 'xray':
            task.add_argument('--select', required=True, help='Shell selection, e.g. colour:15')
            task.add_argument('--colour', default='47', help='Transparent colour code or swatch (default: 47)')
            task.add_argument('--highlight', help='Selection to edge in magenta')
        elif name == 'pivot':
            task.add_argument('--point', required=True, nargs=3, type=float, metavar=('X', 'Y', 'Z'))
            task.add_argument('--direction', required=True, nargs=3, type=float, metavar=('X', 'Y', 'Z'))
            task.add_argument('--moving', required=True, help='Selection that rotates')
            task.add_argument('--hardware', help='Joint hardware selection to edge in magenta')
            task.add_argument('--angles', nargs='+', type=float, default=[0, 45, 90], help='Angles in degrees (default: 0 45 90)')
        elif name == 'cutaway':
            task.add_argument('--view', choices=VIEWS[1:], default='front', help='Axis-aligned view (default: front)')
            task.add_argument('--depths', nargs='+', type=float, default=[0.35, 0.5, 0.65], help='Depths from 0 to 1 (default: .35 .5 .65)')

    mosaic = command('mosaic', 'Compose existing images from a render or panel manifest')
    mosaic.add_argument('manifest')
    mosaic.add_argument('-o', '--output', required=True, help='Output PNG file')
    mosaic.add_argument('--columns', type=int, default=2)
    mosaic.add_argument('--panel-width', type=int, default=800)
    mosaic.add_argument('--force', action='store_true')
    _model(command('connections', 'Report contacts, connected groups, and overlap candidates'))
    _model(command('axes', 'Propose rotation axes from coaxial connectors'))
    return root


def _config_options(args):
    values = vars(args)
    if values.get('shadow') and values.get('no_shadow'):
        raise ValueError('Choose --shadow or --no-shadow, not both')
    return dict(library=values.get('library'), shadows=values.get('shadow'),
                leocad=values.get('leocad'), cache_dir=values.get('cache_dir'),
                no_shadow=values.get('no_shadow', False))


def _config(args):
    options = _config_options(args)
    return XrayConfig.resolve(options.pop('library'), **options)


def _subject(args):
    source = Path(args.file).expanduser().resolve()
    doc = Document.read(source)
    section = doc.model_section(args.section).name
    parent = getattr(args, 'parent', None)
    if parent is not None:
        parent = doc.parent_name(section, None if parent is True else parent)
    return source, section, parent


def _render_layers(args):
    layers = []
    if args.xray is not None:
        layers.append(dict(layer='xray', select=args.xray))
    elif args.stud_map:
        layers.append(dict(layer='stud_map'))
    if hasattr(args, 'steps'):
        layers.append(dict(layer='steps', **({} if args.steps == 'all' else {'numbers': args.steps})))
    if args.highlight is not None:
        layers.append(dict(layer='highlight', select=args.highlight))
    if args.ghost:
        layers.append(dict(layer='ghost'))
    return layers


def _preset(args):
    from . import presets
    # Presets consider only useful parents unless the user explicitly names one.
    parent = getattr(args, 'parent', None)
    if parent is True:
        _, _, parent = _subject(args)
    if args.task == 'overview':
        return presets.overview(args.file, args.section, steps=getattr(args, 'steps', ()), parent=parent)
    if args.task == 'stud-map':
        return presets.stud_map(args.file, args.section, steps=getattr(args, 'steps', ()), parent=parent)
    if args.task == 'xray':
        return presets.xray(args.file, args.section, select=args.select, colour=args.colour, highlight=args.highlight)
    if args.task == 'pivot':
        return presets.pivot(args.file, args.section, point=args.point, direction=args.direction,
                             moving=args.moving, hardware=args.hardware, angles=args.angles, parent=parent)
    return presets.cutaway(args.file, args.section, view=args.view, depths=args.depths)


def run(args):
    if args.command == 'doctor':
        return doctor(args)
    if args.command == 'sections':
        doc = Document.read(args.file)
        return dict(file=str(Path(args.file).resolve()), sections=[
            dict(name=block.name, kind='part' if block.is_part else 'model', first_line=block.first_line,
                 placements=len(block.placements()), steps=block.step_count(),
                 empty_leading_steps=block.empty_leading_steps(), parents=list(doc.parents_of(block.name)))
            for block in (doc.blocks[key] for key in doc.order)
        ])
    if args.command == 'palette':
        from .palette import SWATCHES, check_palette
        result = dict(swatches=[dict(name=s.name, code=s.code, value=s.value, meaning=s.meaning, alpha=s.alpha) for s in SWATCHES])
        if args.check:
            from .library import _ldconfig
            result['check'] = check_palette(_ldconfig(_config(args).ldraw_lib))
        return result
    if args.command == 'mosaic':
        from .mosaic import compose_mosaic
        return compose_mosaic(args.manifest, args.output, columns=args.columns,
                              panel_width=args.panel_width, force=args.force)

    from .board import summary
    from .render import Session
    if args.command == 'render':
        from .layers import validate_layers
        layers = validate_layers(_render_layers(args))
        source, section, parent = _subject(args)
        session = Session(_config(args))
        return summary(session.render(source, output=args.output, section=section, parent=parent,
                                      layers=layers, views=args.view or ['home'], force=args.force,
                                      keep_intermediates=args.keep_intermediates))
    if args.command == 'board':
        recipe = args.recipe if args.task == 'run' else _preset(args)
        session = Session(_config(args))
        return summary(session.board(recipe, output=args.output, force=args.force,
                                     keep_intermediates=args.keep_intermediates,
                                     mosaic=False if args.no_mosaic else None))
    from . import connections
    source, section, _ = _subject(args)
    session = Session(_config(args))
    if args.command == 'axes':
        return connections.propose_axes(session.parts, source, section)
    return connections.report(session.parts, source, section, shadows=session.config.shadows)


def doctor(args):
    from .layers import LAYERS
    from .leocad import TESTED_VERSIONS, version
    from .manifest import versions
    found, errors = discover(**_config_options(args))
    installed = versions()
    if found['leocad'] is not None:
        try:
            installed['leocad'] = version(found['leocad'])
        except (OSError, subprocess.SubprocessError) as error:
            errors['leocad'] = str(error)
    renders = not errors and found['library'] is not None and found['leocad'] is not None
    result = dict(**found, versions=installed, errors=errors, renders=renders,
                  layers=list(LAYERS) if renders else [],
                  connection_overlays='LDCad shadow metadata' if found['shadows'] else 'Built-in detection; set LDRAW_SHADOW for more coverage')
    if found['library'] is not None:
        result['parts'] = sum(1 for _ in (found['library'] / 'parts').glob('*.dat'))
    if installed.get('leocad') and installed['leocad'] not in TESTED_VERSIONS:
        result['warning'] = f'LeoCAD {installed["leocad"]} is untested; tested: {", ".join(TESTED_VERSIONS)}'
    return result


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        result = run(args)
    except (ValueError, KeyError, FileNotFoundError) as error:
        print(json.dumps(dict(error=str(error).strip('"'))), file=sys.stderr)
        return 2
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(error=str(error))), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
