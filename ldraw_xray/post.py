"""Post-processing of LeoCAD's transparent PNGs into images an agent can read.

Flattening on a light backdrop keeps ghosted and transparent parts visible
(the same image on dark grey lost 76% of a ghosted parent's outline). The
outline is traced from opaque pixels only: LDraw draws no edge lines along
curved silhouettes, so white curved shells vanish on light backdrops, while
tracing semi-transparent pixels turns ghosted context into speckle.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter


def flatten(rgba: Image.Image, backdrop='#EEF1F4', outline='#2A2F36', width=2, threshold=250) -> Image.Image:
    rgba = rgba.convert('RGBA')
    base = Image.new('RGBA', rgba.size, backdrop)
    if outline and width > 0:
        solid = np.array(rgba)[..., 3] >= threshold
        grown = np.array(Image.fromarray((solid * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * width + 1))) > 0
        layer = Image.new('RGBA', rgba.size, outline)
        layer.putalpha(Image.fromarray(((grown & ~solid) * 255).astype(np.uint8)))
        base.alpha_composite(layer)
    base.alpha_composite(rgba)
    return base.convert('RGB')


def coverage(rgba: Image.Image):
    """Share of the frame covered by the model (alpha > 0), for framing notes."""
    a = np.array(rgba.convert('RGBA'))[..., 3]
    return round(float((a > 0).mean()), 4)
