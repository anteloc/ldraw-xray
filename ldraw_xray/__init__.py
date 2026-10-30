"""ldraw-xray: composable LeoCAD inspection renders for agents with vision.

    from ldraw_xray import Session, Scene
    s = Session()                                   # LDRAW_DIR, LDRAW_SHADOW, LEOCAD from the environment
    s.render(Scene('model.mpd', 'wing.ldr'), ['stud_map', 'highlight:sel=step:3'], ['home', 'front'], 'out/')
"""
from .board import run_board, summary
from .camera import Camera
from .config import ConfigError, XrayConfig
from .layers import Build, Scene, parse_layer
from .leocad import Style
from .mosaic import compose_mosaic
from .presets import PRESETS
from .render import Session

__all__ = ['Build', 'Camera', 'ConfigError', 'PRESETS', 'Scene', 'Session', 'Style', 'XrayConfig', 'compose_mosaic',
           'parse_layer', 'run_board', 'summary']
