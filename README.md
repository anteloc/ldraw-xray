# ldraw-xray

Render LDraw models with LeoCAD so an agent can inspect their geometry. Highlight
parts, see through a shell, inspect source steps, or make a labelled inspection
board. The source model and parts library are never modified.

## Install

Requires Python ≥3.12, an LDraw parts library, and LeoCAD (tested with 25.09).

```sh
uv venv
uv pip install -e '.[test]'
source .venv/bin/activate
export LDRAW_DIR=/path/to/ldraw
ldraw-xray doctor
```

`doctor` reports missing dependencies even when setup is incomplete. Optionally
set `LDRAW_SHADOW` to an LDCad shadow library for better connector coverage.

| Setting | Flag | Environment | Default |
|---|---|---|---|
| Parts library | `--library` | `LDRAW_DIR`, then `LDRAWDIR` | Required for rendering |
| Shadow libraries | Repeat `--shadow`; `--no-shadow` disables them | `LDRAW_SHADOW`, separated by the OS path separator | Built-in connector detection |
| LeoCAD executable | `--leocad` | `LEOCAD` | PATH, then the macOS app |
| Index cache | `--cache-dir` | `LDRAW_XRAY_CACHE` | User cache directory |

Flags override environment variables. Configuration flags work before the
command or after its final subcommand. `python -m ldraw_xray` is equivalent to
`ldraw-xray`.

## First render

```sh
ldraw-xray sections model.mpd
ldraw-xray render model.mpd --output out/
ldraw-xray render model.mpd --section wing.ldr --view home --view front --output views/
ldraw-xray render model.mpd --section wing.ldr --highlight 'step:3' --ghost --output highlight/
ldraw-xray render model.mpd --section wing.ldr --parent --highlight section --ghost --output context/
```

Omit `--section` for the root model and `--view` for the home view. Bare
`--parent` uses the unique parent; if several parents exist, the error lists
them so you can choose `--parent NAME`.

| Render flag | Effect |
|---|---|
| `--highlight SELECTOR` | Magenta edges on selected parts |
| `--ghost` | Fade everything outside the highlight; requires `--highlight` |
| `--xray SELECTOR` | Make selected parts transparent |
| `--stud-map` | Colour parts by stud direction |
| `--steps [NUMBERS]` | One image per source step, e.g. `--steps 3,7-9`; bare `--steps` includes all nonempty steps |

X-ray and stud mapping are alternatives on the CLI. They run before highlighting
and ghosting. Steps cannot combine with highlight or ghost and require an
isolated section. Repeated `--view` flags produce the requested views.

## Inspection boards

Each task exposes only its relevant options; use `board TASK --help` for details.

```sh
ldraw-xray board overview model.mpd --section wing.ldr --steps 3,7 --output overview/
ldraw-xray board stud-map model.mpd --section wing.ldr --output studs/
ldraw-xray board xray model.mpd --select 'colour:15' --highlight 'colour:4' --output xray/
ldraw-xray board pivot model.mpd --point 0 -18 0 --direction 0 0 1 --moving '!part:3894' --output pivot/
ldraw-xray board cutaway model.mpd --view front --depths 0.35 0.5 0.65 --output cuts/
ldraw-xray board run overview/recipe.json --output replay/
```

Overview, stud-map, and pivot boards include useful parent context when unique.
They omit it when none exists and require `--parent NAME` when ambiguous.
Use `--no-mosaic` for panels only. Edit the saved recipe for advanced layers,
styles, or cameras; see the [reference](docs/reference.md).

## Select parts

Quote selectors in a shell, especially when they contain `*`, `!`, or `|`.

| Selector | Selects |
|---|---|
| `all` | Every placement |
| `section` | Placements of the inspected section inside its parent |
| `line:12,15,20-24` | Source-file line numbers |
| `step:3-5` | Source step numbers, including empty steps in the numbering |
| `part:3001*` | Part-reference glob; `.dat` is optional |
| `colour:15,4` | Colour codes written on placement lines |
| `ref:wing.ldr` | Exact part or submodel reference |

`|` includes either term; `!` excludes a term. For example,
`'part:3001*|colour:15|!step:1'`. Exclusions apply after all inclusions; a selector
containing only exclusions starts from `all`. Empty selections are reported in
the image's notes.

## Outputs and data commands

Every render or board writes `panels/`, a replayable `recipe.json`, and one
`manifest.json`. Boards with 2–12 images also write `mosaic.png`; larger jobs
need `--no-mosaic`. `--keep-intermediates` adds transparent PNGs, synthetic models,
and a source-section copy under `intermediates/`.

`--force` replaces generated files while preserving unrelated files. Requests
are validated before rendering; completed jobs are staged before publication.
Saved recipes resolve the source path, section, parents, and render settings.
Manifest artifact paths are relative to the output directory; CLI results give
absolute paths.

```sh
ldraw-xray connections model.mpd --section wing.ldr
ldraw-xray axes model.mpd --section wing.ldr
ldraw-xray palette --check
ldraw-xray mosaic views/manifest.json --output mosaic.png
```

`sections`, `palette` without `--check`, and `mosaic` do not need LeoCAD or a
parts library. The standalone mosaic command writes its metadata to a JSON
file beside the PNG.

Commands print one JSON result to stdout. Errors are JSON on stderr: exit 2
means invalid input or configuration; exit 1 means execution failed. Help is
plain text. Renders show geometry; connection reports and overlap candidates
are evidence to inspect, not proof of fit, clutch, or stability.

## Python

```python
from pathlib import Path
from ldraw_xray import Session

session = Session()
manifest = session.render(
    "model.mpd",
    section="wing.ldr",
    output="out",
    layers=[{"layer": "xray", "select": "colour:15"}],
    views=["home", "front"],
)
images = [Path(manifest["output"]) / panel["image"] for panel in manifest["panels"]]
session.board("out/recipe.json", output="replay")
```

`XrayConfig`, `Style`, `Camera`, and `compose_mosaic` are also public APIs.
Advanced Python calls use the same layer objects as recipes.

## Development and licence

Run `python -m pytest -q`. Renderer, library, and shadow tests skip when their
external dependencies are unavailable. CLI and recipe tests use small fixtures.

Code: AGPL-3.0 ([LICENSE](LICENSE)). Documentation: CC BY-SA 4.0
([CC-BY-SA-4.0](CC-BY-SA-4.0)). The mosaic composer and pyldraw3 connection-frame
adapter are adapted from ldraw-nova by the same author.
