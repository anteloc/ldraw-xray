"""Render and inspect LDraw models with LeoCAD.

    from ldraw_xray import Session
    manifest = Session().render("model.mpd", output="out", layers=[{"layer": "stud_map"}])
"""
from .camera import Camera
from .config import ConfigError, XrayConfig
from .leocad import Style
from .mosaic import compose_mosaic
from .render import Session

__all__ = ['Camera', 'ConfigError', 'Session', 'Style', 'XrayConfig', 'compose_mosaic']
