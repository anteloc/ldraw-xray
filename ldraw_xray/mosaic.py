"""Labelled inspection boards composed from full-resolution renders.

Ported from ldraw-nova's `ldraw_tools/mosaic.py` (same author, AGPL-3.0) with:
word wrapping that never splits words, a light panel backdrop, up to 12 panels,
optional legend lines, and a duplicate-panel check.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .library import atomic_write

PAGE = '#eef1f4'
INK = '#17272c'
DUPLICATE_THRESHOLD = 7.0   # mean absolute difference of 96x72 RGB thumbnails (0-255)


def thumbnail_difference(a: Image.Image, b: Image.Image):
    def thumb(im):
        base = Image.new('RGBA', im.size, 'white')
        base.alpha_composite(im.convert('RGBA'))
        return np.asarray(base.convert('RGB').resize((96, 72), Image.Resampling.BILINEAR), dtype=float)
    return float(np.abs(thumb(a) - thumb(b)).mean())


def _lines(draw, text, width, font):
    """Greedy word wrap; a single word longer than the width is split as a last resort."""
    result, current = [], ''
    for word in text.split():
        trial = (current + ' ' + word) if current else word
        if draw.textlength(trial, font=font) <= width:
            current = trial
            continue
        if current:
            result.append(current)
        current = ''
        while draw.textlength(word, font=font) > width:
            cut = max(1, next(i for i in range(len(word), 0, -1) if draw.textlength(word[:i], font=font) <= width))
            result.append(word[:cut])
            word = word[cut:]
        current = word
    return result + ([current] if current else [])


def compose_mosaic(manifest, output, *, columns=2, panel_width=800, force=False, backdrop=PAGE):
    """Compose a board from a panel manifest (JSON file or dict with a `base` directory).

    Manifest: {title, mode: views|analysis, legend?: [str], panels: [{image, label, camera?, subject?, state?}]}.
    Analysis mode requires one shared camera and subject plus identical image sizes.
    """
    if isinstance(manifest, dict):
        spec, base, manifest_path = manifest, Path(manifest.get('base', '.')).resolve(), None
    else:
        manifest_path = Path(manifest).resolve()
        spec, base = json.loads(manifest_path.read_text()), manifest_path.parent
    output = Path(output).resolve()
    sidecar = output.with_suffix('.json')
    panels, mode = spec.get('panels'), spec.get('mode', 'views')
    if mode not in {'views', 'analysis'}:
        raise ValueError('Mosaic mode must be views or analysis')
    if not isinstance(panels, list) or not 2 <= len(panels) <= 12:
        raise ValueError('Choose 2 to 12 panels')
    if not 1 <= columns <= 4 or not 320 <= panel_width <= 1600:
        raise ValueError('Use 1-4 columns and panel width 320-1600')
    if output.suffix.lower() != '.png':
        raise ValueError('Mosaic output must be a PNG')
    title = spec.get('title', 'Inspection mosaic')
    if not isinstance(title, str) or len(title) > 120:
        raise ValueError('Mosaic title must be text of at most 120 characters')
    images, entries, inputs = [], [], {manifest_path} if manifest_path else set()
    for panel in panels:
        if not isinstance(panel, dict) or not isinstance(panel.get('image'), str):
            raise ValueError('Each panel needs an image path')
        label = panel.get('label')
        if not isinstance(label, str) or not label.strip() or len(label) > 200:
            raise ValueError('Each panel needs a nonempty label of at most 200 characters')
        path = (base / panel['image']).resolve()
        inputs.add(path)
        data = path.read_bytes()
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > 24_000_000:
                raise ValueError('Panel exceeds 24 megapixels')
            image = source.convert('RGBA')
        flat = Image.new('RGBA', image.size, backdrop)
        flat.alpha_composite(image)
        images.append(flat.convert('RGB'))
        entries.append(dict(panel=len(entries) + 1, label=label, image=str(path), sha256=hashlib.sha256(data).hexdigest(),
                            size=list(image.size), camera=panel.get('camera'), subject=panel.get('subject'),
                            state=panel.get('state')))
    if output in inputs or sidecar in inputs:
        raise ValueError('Mosaic outputs must not overwrite inputs')
    if not force and (output.exists() or sidecar.exists()):
        raise ValueError('Mosaic output exists; use force')
    if mode == 'analysis':
        first = panels[0]
        if not isinstance(first.get('camera'), dict) or not first['camera'] or not first.get('subject'):
            raise ValueError('Analysis panels need camera metadata and a common subject identifier')
        if any(p.get('camera') != first['camera'] or p.get('subject') != first['subject'] for p in panels):
            raise ValueError('Analysis panels must declare the same camera and subject coordinate frame')
        if any(im.size != images[0].size for im in images):
            raise ValueError('Analysis panels must have identical source image dimensions')
    duplicates = []
    for i in range(len(images)):
        for j in range(i + 1, len(images)):
            d = thumbnail_difference(images[i], images[j])
            if d < DUPLICATE_THRESHOLD:
                duplicates.append(dict(panels=[i + 1, j + 1], difference=round(d, 1)))

    height = round(panel_width * 0.75)
    gap, caption, heading = 16, 96, 96
    legend = [str(l) for l in spec.get('legend', [])][:4]
    footer = 26 * len(legend) + (16 if legend else 0)
    columns = min(columns, len(panels))
    rows = math.ceil(len(panels) / columns)
    board = Image.new('RGB', (columns * (panel_width + gap) + gap, heading + rows * (height + caption + gap) + footer), PAGE)
    draw = ImageDraw.Draw(board)
    font = ImageFont.load_default(size=20)
    title_font = ImageFont.load_default(size=26)
    small = ImageFont.load_default(size=16)
    for n, line in enumerate(_lines(draw, title, board.width - 2 * gap, title_font)[:2]):
        draw.text((gap, 8 + n * 28), line, font=title_font, fill=INK)
    note = ('Aligned by supplied camera metadata; one camera for every panel.' if mode == 'analysis'
            else 'Views independently framed; not to common scale.')
    draw.text((gap, 68), note, font=ImageFont.load_default(size=14), fill='#394952')
    for i, (im, entry) in enumerate(zip(images, entries)):
        x, y = gap + (i % columns) * (panel_width + gap), heading + (i // columns) * (height + caption + gap)
        fitted = ImageOps.contain(im, (panel_width, height), Image.Resampling.LANCZOS)
        draw.rectangle((x - 1, y - 1, x + panel_width, y + height), fill=backdrop, outline='#c3ccd4')
        left, top = x + (panel_width - fitted.width) // 2, y + (height - fitted.height) // 2
        board.paste(fitted, (left, top))
        entry['image_box'] = [left, top, fitted.width, fitted.height]
        label_lines = _lines(draw, f'{i + 1}. {entry["label"]}', panel_width - 12, font)
        if len(label_lines) > 4:
            raise ValueError(f'Panel {i + 1} label is too long for this width; shorten it or widen the panels')
        for n, line in enumerate(label_lines):
            draw.text((x + 6, y + height + 6 + n * 22), line, font=font, fill=INK)
    for n, line in enumerate(legend):
        draw.text((gap, board.height - footer + 8 + n * 26), line, font=small, fill=INK)
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(suffix='.png', dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        board.save(temporary, format='PNG')
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    report = dict(version=1, output=str(output), mode=mode, title=title, size=list(board.size), columns=columns,
                  panels=entries, legend=legend, duplicates=duplicates, note=note,
                  manifest=str(manifest_path) if manifest_path else None,
                  manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest_path else None,
                  image_sha256=hashlib.sha256(output.read_bytes()).hexdigest(), visual_review='pending',
                  limitations=['Boards do not prove fit, clearance or stability; inspect full-resolution panels for small details.'])
    atomic_write(sidecar, json.dumps(report, indent=2) + '\n')
    return report
