"""Out-of-band inspection colours: deliberately not LEGO catalogue colours.

Each value is at least CIE76 dE 16 from every LDConfig.ldr colour of the current
LDraw library (checked by `check_palette`) so a recoloured part is never mistaken
for a real part colour. LeoCAD ignores direct colours (0x2RRGGBB) and model-local
!COLOUR lines, so renders use a wrapper library whose LDConfig.ldr adds these codes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Swatch:
    name: str
    code: int
    value: str
    meaning: str
    alpha: int | None = None
    edge: str = '#333333'

    def ldconfig(self):
        line = f'0 !COLOUR {self.name} CODE {self.code} VALUE {self.value} EDGE {self.edge}'
        return line + (f' ALPHA {self.alpha}' if self.alpha is not None else '')


SWATCHES = [
    # Stud-direction map (section or parent frame; LDraw -Y is up).
    Swatch('Xray_Studs_Up', 9007, '#EDD4F7', 'studs point up (-Y)'),
    Swatch('Xray_Studs_PlusX', 9001, '#FF0078', 'studs point +X'),
    Swatch('Xray_Studs_MinusX', 9002, '#FF5500', 'studs point -X'),
    Swatch('Xray_Studs_PlusZ', 9003, '#0500FF', 'studs point +Z', edge='#9090FF'),
    Swatch('Xray_Studs_MinusZ', 9004, '#00FFE0', 'studs point -Z'),
    Swatch('Xray_Studs_Down', 9005, '#BCF747', 'studs point down (+Y)'),
    Swatch('Xray_Studs_Angled', 9006, '#7C49FF', 'studs at an odd angle'),
    # Markers.
    Swatch('Xray_Axis', 9008, '#39FF14', 'synthetic axis rod (not a part)'),
    # Agent-defined groups (recolour layer, connected components).
    Swatch('Xray_Group_A', 9011, '#3370FF', 'group A'),
    Swatch('Xray_Group_B', 9012, '#00FFA6', 'group B'),
    Swatch('Xray_Group_C', 9013, '#66540A', 'group C'),
    Swatch('Xray_Group_D', 9014, '#00E6FF', 'group D'),
    Swatch('Xray_Group_E', 9015, '#EC80FF', 'group E'),
    Swatch('Xray_Group_F', 9016, '#6847B2', 'group F'),
    # Connection overlays.
    Swatch('Xray_Contact_Confirmed', 9021, '#00B236', 'contact point, confirmed connection'),
    Swatch('Xray_Contact_Heuristic', 9022, '#A6B236', 'contact point, heuristic or potential connection'),
    Swatch('Xray_Collision', 9023, '#B2124A', 'overlap candidate (not proven)'),
    # See-through alternative to LEGO Trans-Clear (47).
    Swatch('Xray_Glass', 9031, '#8099FF', 'x-ray glass (synthetic transparency)', alpha=110),
]
BY_NAME = {s.name: s for s in SWATCHES}
BY_CODE = {s.code: s for s in SWATCHES}
DIRECTION_CODES = {'up': 9007, '+x': 9001, '-x': 9002, '+z': 9003, '-z': 9004, 'down': 9005, 'angled': 9006}
GROUP_CODES = [9011, 9012, 9013, 9014, 9015, 9016]
AXIS_CODE = 9008
HIGHLIGHT = '#FF00FF'


def resolve(code):
    """Accept an LDraw code (int/str), a swatch name, or 'group:A'..'group:F'."""
    if isinstance(code, int):
        return code
    text = str(code).strip()
    if text.lstrip('-').isdigit():
        return int(text)
    if text.casefold().startswith('group:'):
        letter = text.split(':', 1)[1].strip().upper()
        return GROUP_CODES['ABCDEF'.index(letter)]
    if text in BY_NAME:
        return BY_NAME[text].code
    raise ValueError(f'Unknown colour {code!r}: use an LDraw code, a swatch name or group:A..F')


def legend(codes):
    return [dict(code=c, value=BY_CODE[c].value, meaning=BY_CODE[c].meaning) for c in sorted(set(codes)) if c in BY_CODE]


def ldconfig_lines():
    return ['0 // ldraw-xray synthetic inspection colours (not LEGO colours)', *(s.ldconfig() for s in SWATCHES)]


def lab(rgb):
    """sRGB (0-255, ...x3) to CIE Lab (D65)."""
    c = np.asarray(rgb, dtype=float) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    xyz = c @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz = xyz / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def hex_rgb(value):
    v = value.lstrip('#')
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def check_palette(ldconfig: Path, minimum=16.0):
    """Nearest LDConfig colour for every swatch; `ok` is False if any is closer than `minimum`."""
    text = Path(ldconfig).read_text(errors='replace')
    names, values = [], []
    for m in re.finditer(r'!COLOUR\s+(\S+)\s+CODE\s+(\d+)\s+VALUE\s+#([0-9A-Fa-f]{6})', text):
        if int(m.group(2)) in BY_CODE:
            continue
        names.append(m.group(1))
        values.append(hex_rgb(m.group(3)))
    lego = lab(np.array(values))
    rows = []
    for s in SWATCHES:
        d = np.sqrt(((lego - lab(np.array(hex_rgb(s.value)))) ** 2).sum(-1))
        i = int(d.argmin())
        rows.append(dict(name=s.name, code=s.code, value=s.value, nearest=names[i], delta_e=round(float(d[i]), 1)))
    return dict(ok=all(r['delta_e'] >= minimum for r in rows), minimum=minimum, swatches=rows)
