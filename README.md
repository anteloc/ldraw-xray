# ldraw-xray

Visual rendering tools tailored for agents to inspect LDraw models.

ldraw-xray renders an LDraw model or one of its submodels through LeoCAD. It
combines **inspection layers**:

- a magenta highlight;
- a ghosted parent;
- x-ray transparency;
- out-of-band (non-LEGO) colouring;
- an axis rod;
- rigid poses;
- cutaways;
- connection overlays.

It writes readable PNGs, a provenance manifest and a labelled mosaic. It is a
Python package and a CLI (`ldraw-xray`), and every command prints one JSON
object.

It only makes pictures and the data a picture needs. It does not judge models:
images come from synthetic copies, never from valid models.

## Install

```sh
uv venv && uv pip install -e '.[test]'
```

**Requirements:**

- Python ≥ 3.12;
- an LDraw parts library;
- LeoCAD (tested with 25.09);
- optionally, an LDCad shadow library for connector metadata.

## Configuration

Each setting is resolved in this order: CLI flag, then environment variable,
then default. The variable names match ldraw-nova's.

| Setting | Flag | Environment | Default |
|---|---|---|---|
| LDraw library (**required**) | `-l`, `--ldraw-lib` | `LDRAW_DIR`, then `LDRAWDIR` | none |
| LDCad shadow library (optional; a directory, `.zip` or `.csl`) | `--shadow` (repeatable), `--no-shadow` | `LDRAW_SHADOW` (`os.pathsep` list) | none |
| LeoCAD | `--leocad` | `LEOCAD` | `leocad` on PATH, then the macOS app |
| Cache for the pyldraw3 index | `--cache-dir` | `LDRAW_XRAY_CACHE` | user cache `ldraw-xray` |

`ldraw-xray doctor` shows what was found and which layers can run.

The library is never written. Renders use a wrapper directory:

- symlinks to the library;
- an `LDConfig.ldr` extended with the xray colours;
- an `unofficial/parts/` folder for embedded and synthetic parts.

## Quick start

```sh
ldraw-xray sections model.mpd                          # find section names, steps, parents
ldraw-xray render model.mpd --section "wing.ldr" --layer stud_map --views home front --out out/
ldraw-xray render model.mpd --section "wing.ldr" --context parent --layer highlight --layer ghost --out out/
ldraw-xray board --preset overview --file model.mpd --section "wing.ldr" --steps 3 7 --out board/
ldraw-xray board board/recipe.json --out board2/       # edit the written recipe, re-run it
```

The same in Python:

```python
from ldraw_xray import Session, Scene
s = Session()                                          # configuration from the environment
s.render(Scene('model.mpd', 'wing.ldr'), ['xray:sel=colour:15', 'highlight:sel=step:3'], ['home'], 'out/')
```

## Layers

Layers apply in order and combine freely. The selection syntax is in the next
section.

| Layer | Options | Shows |
|---|---|---|
| `highlight` | `sel`, `scope` | Selected parts drawn with **magenta edges**. In a parent context, it defaults to the section's placements |
| `ghost` | | Everything not highlighted, faded to light grey |
| `steps` | `first`, `last` | Source steps, one image each; new parts have magenta edges. Isolated section only |
| `xray` | `sel`, `colour` (default 47 Trans-Clear, or `Xray_Glass`) | Selected parts see-through, recursing into children with explicit colours |
| `recolour` | `sel`, `colour` (`group:A`..`F`, a swatch name or a code) | Agent-defined groups in out-of-band colours |
| `stud_map` | `sel` | Each part coloured by where its studs point (legend below) |
| `pose` | `sel`, `point`, `direction`, `angle` | Rigid rotation of the selection about an axis |
| `axis` | `point`, `direction`, `length`, `radius` | **Neon-green rod** along an axis (section coordinates). Shown in parent renders too |
| `closeup` | `sel`, `scope`, `view`, `margin` | Camera fitted to the selection's bounds (useful inside a huge parent) |
| `cutaway` | `view` (axis-aligned), `depth` 0–1 | Camera near plane slices the model open at that depth |
| `components` | | Connected groups except the largest, recoloured (floating groups, or detection gaps) |
| `contacts` | `radius` | Marker spheres at detected connector contacts: green = confirmed, olive = heuristic |
| `collisions` | `min_depth` | Box-overlap candidates without a detected contact, in raspberry |

The CLI form is `name:key=value;key=value`. Vectors are written `x,y,z`, for
example `pose:sel=!part:3894;point=0,-18,0;direction=0,0,1;angle=45`.

## Selections

Terms are combined with `|` (union); `!term` excludes. A selection made only of
exclusions starts from `all`.

| Term | Selects |
|---|---|
| `all` | Every placement |
| `section` | The inspected section's placements, in a parent context |
| `line:12,15,20-24` | Source line numbers |
| `step:3-5` | Source steps (counting every `0 STEP`) |
| `part:3001*` | A glob on the part file name |
| `colour:15,4` | Colour codes |
| `ref:NAME` | An exact reference |

## Presets and boards

`board --preset NAME` writes `recipe.json` and runs it. A board folder contains:

- `panels/` (flattened PNGs; `raw/` holds the transparent originals and
  `synthetic/` the MPDs);
- `manifest.json`;
- `mosaic.png` with its `mosaic.json`.

| Preset | Options | Panels |
|---|---|---|
| `overview` | `--steps` | Parent ghost, isolated home view, chosen steps |
| `snot` | `--steps` | Parent highlight, stud map (home and front), chosen steps |
| `xray` | `--sel`, `--colour`, `--highlight` | As built, then the selection see-through from three views |
| `pivot` | `--point`, `--direction`, `--moving`, `--hardware`, `--angles` | Axis rod + hardware, parent with rod, pose sweep from one fixed camera |
| `cutaway` | `--view`, `--depths` | Uncut view, then cuts at each depth |

`ldraw-xray connections` and `ldraw-xray axes` print the data behind the overlays:

- contacts, connected groups and overlap candidates;
- coaxial-connector axis candidates you can pass to `axis` and `pose`.

## Colours

**Stud map:**

| Studs point | Colour |
|---|---|
| Up | `#EDD4F7` |
| +X | `#FF0078` |
| −X | `#FF5500` |
| +Z | `#0500FF` |
| −Z | `#00FFE0` |
| Down | `#BCF747` |
| Odd angle | `#7C49FF` |

**Other swatches:**

- Axis rod: `#39FF14`.
- Groups A–F: `#3370FF`, `#00FFA6`, `#66540A`, `#00E6FF`, `#EC80FF`, `#6847B2`.
- Contacts: `#00B236` confirmed, `#A6B236` heuristic.
- Collisions: `#B2124A`.
- Glass: `#8099FF`, alpha 110.

Every swatch is at least ΔE 16 (CIE76) from every LDConfig colour; check with
`ldraw-xray palette --check`.

## Render style

The style is pinned because LeoCAD otherwise uses the GUI's saved preferences:

```
--stud-style 6 -aec -cc 1.0 -ldv 0.5 --shading full --aa-samples 4 --line-width 2
```

After rendering, each image is flattened onto `#EEF1F4` with a 2 px `#2A2F36`
outline traced from opaque pixels. Cameras fit the parts' box corners, so nothing
is cropped and the steps of one section share a scale. Override any of these
with `--style key=value`.

See [docs/agents.md](docs/agents.md) for how to choose layers and read the
images.

## Licence

- Code: AGPL-3.0 (`LICENSE`).
- Documentation: CC BY-SA 4.0 (`CC-BY-SA-4.0`).
- The mosaic composer and the pyldraw3 connection-frame adapter are adapted
  from ldraw-nova (same author).
