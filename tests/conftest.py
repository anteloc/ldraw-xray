import os
import shutil
from pathlib import Path

import pytest

# A tiny MPD: a root placing a child twice (once turned 90 degrees about Y), the
# child has explicit and inherited colours over three steps, plus an embedded part.
MODEL = """0 FILE root.ldr
0 Root
0 Name: root.ldr
1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat
0 STEP
1 16 0 -24 0 1 0 0 0 1 0 0 0 1 wing.ldr
1 1 100 -24 0 0 0 1 0 1 0 -1 0 0 wing.ldr
0 STEP
1 15 0 -48 0 1 0 0 0 1 0 0 0 1 marker.dat
0 NOFILE
0 FILE wing.ldr
0 Wing
0 Name: wing.ldr
1 16 0 0 0 1 0 0 0 1 0 0 0 1 3003.dat
0 STEP
0 STEP
1 14 20 -8 0 1 0 0 0 1 0 0 0 1 3022.dat
0 STEP
1 2 -20 -8 0 0 1 0 -1 0 0 0 0 1 3024.dat
0 NOFILE
0 FILE marker.dat
0 Embedded part
0 Name: marker.dat
1 16 0 0 0 1 0 0 0 1 0 0 0 1 3005.dat
0 NOFILE
"""


@pytest.fixture
def model(tmp_path):
    path = tmp_path / 'model.mpd'
    path.write_text(MODEL)
    return path


def _library():
    path = os.environ.get('LDRAW_DIR') or os.environ.get('LDRAWDIR')
    return Path(path) if path and (Path(path) / 'parts').is_dir() else None


@pytest.fixture
def library():
    lib = _library()
    if lib is None:
        pytest.skip('needs an LDraw library (LDRAW_DIR)')
    return lib


@pytest.fixture
def session(library, tmp_path):
    from ldraw_xray import Session, XrayConfig
    config = XrayConfig.resolve(library, None, None, tmp_path / 'cache')
    if config.leocad is None:
        pytest.skip('needs LeoCAD')
    return Session(config)


@pytest.fixture
def shadow_config(library, tmp_path):
    from ldraw_xray import XrayConfig
    if not os.environ.get('LDRAW_SHADOW'):
        pytest.skip('needs an LDCad shadow library (LDRAW_SHADOW)')
    return XrayConfig.resolve(library, None, None, tmp_path / 'cache')


def fake_library(root: Path):
    for d in ('parts', 'p'):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / 'LDConfig.ldr').write_text('0 !COLOUR Black CODE 0 VALUE #1B2A34 EDGE #808080\n'
                                       '0 !COLOUR White CODE 15 VALUE #F4F4F4 EDGE #333333\n')
    return root


@pytest.fixture
def fake_lib(tmp_path):
    return fake_library(tmp_path / 'ldraw')


def has_leocad():
    return shutil.which('leocad') is not None or Path('/Applications/LeoCAD.app/Contents/MacOS/LeoCAD').is_file()
