"""ldraw-xray command line. Every command prints one JSON object on stdout."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ConfigError, XrayConfig
from .leocad import Style


def _vector(text):
    return tuple(float(v) for v in text.split(','))


def parser():
    p = argparse.ArgumentParser(prog='ldraw-xray', description='Composable LeoCAD inspection renders for agents with vision.')
    p.add_argument('-l', '--ldraw-lib', '--library', dest='ldraw_lib', help='LDraw library root (default LDRAW_DIR, then LDRAWDIR)')
    shadows = p.add_mutually_exclusive_group()
    shadows.add_argument('--shadow', action='append', help='LDCad shadow library dir/zip/csl; repeatable; replaces LDRAW_SHADOW')
    shadows.add_argument('--no-shadow', action='store_true', help='Ignore LDRAW_SHADOW')
    p.add_argument('--leocad', help='LeoCAD executable (default LEOCAD, then PATH, then the macOS app)')
    p.add_argument('--cache-dir', help='Cache for the pyldraw3 index (default LDRAW_XRAY_CACHE or the user cache)')
    sub = p.add_subparsers(dest='command', required=True)

    sub.add_parser('doctor', help='Check the library, shadow library, LeoCAD and pyldraw3')
    c = sub.add_parser('palette', help='List the out-of-band colours; --check measures them against LDConfig')
    c.add_argument('--check', action='store_true')
    c = sub.add_parser('sections', help='List FILE blocks with steps, part counts and parents')
    c.add_argument('file')

    c = sub.add_parser('render', help='Render one scene with layers from one or more views')
    c.add_argument('file')
    c.add_argument('--section', required=True)
    c.add_argument('--context', choices=['isolate', 'parent'], default='isolate')
    c.add_argument('--parent', help='Parent block (default: the first block that places the section)')
    c.add_argument('--layer', action='append', default=[], help='Repeatable, applied in order, e.g. "xray:sel=colour:15"')
    c.add_argument('--views', nargs='+', default=['home'])
    c.add_argument('--out', required=True)
    c.add_argument('--name')
    c.add_argument('--style', action='append', default=[], help='Style override key=value, e.g. line_width=1')

    c = sub.add_parser('board', help='Render a recipe (or a preset) into panels, a manifest and a mosaic')
    c.add_argument('recipe', nargs='?', help='Recipe JSON (omit with --preset)')
    c.add_argument('--preset', choices=['overview', 'snot', 'xray', 'pivot', 'cutaway'])
    c.add_argument('--file', help='Model for --preset')
    c.add_argument('--section', help='Section for --preset')
    c.add_argument('--parent')
    c.add_argument('--steps', nargs='*', type=int, default=[])
    c.add_argument('--sel', help='xray: the shell to see through')
    c.add_argument('--colour', default='47', help='xray colour (LDraw code or swatch name)')
    c.add_argument('--highlight', help='xray: parts to edge magenta')
    c.add_argument('--point', type=_vector, help='pivot: axis point x,y,z (section frame)')
    c.add_argument('--direction', type=_vector, help='pivot: axis direction x,y,z')
    c.add_argument('--moving', help='pivot: selection that rotates')
    c.add_argument('--hardware', help='pivot: selection edged magenta')
    c.add_argument('--angles', nargs='+', type=float, default=[0, 45, 90])
    c.add_argument('--view', default='front', help='cutaway view')
    c.add_argument('--depths', nargs='+', type=float, default=[0.35, 0.5, 0.65])
    c.add_argument('--out', required=True)
    c.add_argument('--force', action='store_true')
    c.add_argument('--no-mosaic', action='store_true')

    c = sub.add_parser('mosaic', help='Compose existing images from a panel manifest')
    c.add_argument('manifest')
    c.add_argument('--output', required=True)
    c.add_argument('--columns', type=int, default=2)
    c.add_argument('--panel-width', type=int, default=800)
    c.add_argument('--force', action='store_true')

    c = sub.add_parser('connections', help='Contacts, connected groups and overlap candidates of a section (pyldraw3)')
    c.add_argument('file')
    c.add_argument('--section', required=True)
    c = sub.add_parser('axes', help='Propose rotation axes from coaxial connectors (needs a shadow library for coverage)')
    c.add_argument('file')
    c.add_argument('--section', required=True)
    return p


def _style(pairs):
    data = {}
    for pair in pairs:
        k, _, v = pair.partition('=')
        field = Style.__dataclass_fields__.get(k)
        if field is None:
            raise ValueError(f'Unknown style key {k!r}')
        default = field.default
        data[k] = v if isinstance(default, str) or default is None else type(default)(v if not isinstance(default, bool) else v.lower() in ('1', 'true', 'yes'))
    return Style.from_dict(data)


def _config(args, *, need_library=True):
    return XrayConfig.resolve(args.ldraw_lib, args.shadow, args.leocad, args.cache_dir, no_shadow=args.no_shadow)


def run(args):
    if args.command == 'palette':
        from .palette import SWATCHES, check_palette
        out = dict(swatches=[dict(name=s.name, code=s.code, value=s.value, meaning=s.meaning, alpha=s.alpha) for s in SWATCHES])
        if args.check:
            cfg = _config(args)
            from .library import _ldconfig
            out['check'] = check_palette(_ldconfig(cfg.ldraw_lib))
        return out
    if args.command == 'mosaic':
        from .mosaic import compose_mosaic
        return compose_mosaic(args.manifest, args.output, columns=args.columns, panel_width=args.panel_width, force=args.force)
    if args.command == 'sections':
        from .mpd import Document
        doc = Document.read(args.file)
        rows = []
        for k in doc.order:
            b = doc.blocks[k]
            rows.append(dict(name=b.name, kind='part' if b.is_part else 'model', first_line=b.first_line,
                             placements=len(b.placements()), steps=b.step_count(),
                             empty_leading_steps=b.empty_leading_steps(), parents=list(doc.parents_of(b.name))))
        return dict(file=str(Path(args.file).resolve()), sections=rows)

    config = _config(args)
    if args.command == 'doctor':
        return doctor(config)
    from .render import Session
    if args.command == 'render':
        from .layers import Scene
        session = Session(config, _style(args.style))
        scene = Scene(Path(args.file).resolve(), args.section, args.context, args.parent)
        records = session.render(scene, args.layer, args.views, args.out, name=args.name)
        return dict(images=[dict(image=r['image'], view=r['view'], step=r['step'], legend=r['legend'], notes=r['notes'] or None,
                                 warnings=r['warnings'] or None, layers=r['layers']) for r in records],
                    synthetic=records[0]['synthetic'] if records else None)
    if args.command == 'board':
        from .board import run_board, summary
        if args.preset:
            from .presets import PRESETS
            if not (args.file and args.section):
                raise ValueError('--preset needs --file and --section')
            recipe = PRESETS[args.preset](Path(args.file).resolve(), args.section, steps=args.steps, parent=args.parent,
                                          sel=args.sel, colour=args.colour, highlight=args.highlight, point=args.point,
                                          direction=args.direction, moving=args.moving, hardware=args.hardware,
                                          angles=args.angles, view=args.view, depths=args.depths)
            base = Path.cwd()
        elif args.recipe:
            recipe = json.loads(Path(args.recipe).read_text())
            base = Path(args.recipe).resolve().parent
        else:
            raise ValueError('Give a recipe file or --preset')
        manifest = run_board(recipe, args.out, session=Session(config), base=base, force=args.force, mosaic=not args.no_mosaic)
        return dict(out=str(Path(args.out).resolve()), recipe=str(Path(args.out).resolve() / 'recipe.json'), **summary(manifest))
    if args.command in ('connections', 'axes'):
        from . import connections
        session = Session(config)
        if args.command == 'axes':
            return connections.propose_axes(session.parts, args.file, args.section)
        return connections.report(session.parts, args.file, args.section, shadows=config.shadows)
    raise ValueError(f'Unknown command {args.command}')


def doctor(config: XrayConfig):
    from .manifest import versions
    from .leocad import TESTED_VERSIONS
    v = versions(config)
    parts_count = sum(1 for _ in (config.ldraw_lib / 'parts').glob('*.dat'))
    layers = ['highlight', 'ghost', 'steps', 'xray', 'recolour', 'stud_map', 'pose', 'axis', 'closeup', 'cutaway',
              'contacts', 'components', 'collisions']
    out = dict(ldraw_lib=str(config.ldraw_lib), parts=parts_count, shadows=[str(s) for s in config.shadows],
               leocad=str(config.leocad) if config.leocad else None, versions=v, cache_dir=str(config.cache_dir),
               renders=config.leocad is not None, layers=layers if config.leocad else [],
               connection_overlays='LDCad shadow metadata loaded' if config.shadows else 'built-in connector detection only (set LDRAW_SHADOW for LDCad metadata)')
    if config.leocad and v.get('leocad') not in TESTED_VERSIONS:
        out['warning'] = f'LeoCAD {v.get("leocad")} is untested; tested: {", ".join(TESTED_VERSIONS)}'
    return out


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = run(args)
    except (ConfigError, ValueError, KeyError, RuntimeError) as e:
        print(json.dumps(dict(error=str(e).strip('"')), indent=2))
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
