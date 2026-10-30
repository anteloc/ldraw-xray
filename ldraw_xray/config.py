"""Where the LDraw library, LDCad shadow library, LeoCAD and the cache live.

Precedence is always: explicit argument, then environment variable, then default.
The environment names match ldraw-nova so both tools share one setup.
"""
from __future__ import annotations

import os
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MAC_LEOCAD = Path('/Applications/LeoCAD.app/Contents/MacOS/LeoCAD')


class ConfigError(ValueError):
    """A required path is missing or invalid."""


def _library(value):
    path = value or os.environ.get('LDRAW_DIR') or os.environ.get('LDRAWDIR')
    if not path:
        raise ConfigError('Set LDRAW_DIR (or LDRAWDIR) to the LDraw parts library, or pass --library')
    root = Path(path).expanduser().resolve()
    names = {p.name.casefold() for p in root.iterdir()} if root.is_dir() else set()
    if not {'parts', 'p', 'ldconfig.ldr'} <= names:
        raise ConfigError(f'Not an LDraw library (needs parts/, p/ and LDConfig.ldr): {root}')
    return root


def _shadows(values):
    """None reads LDRAW_SHADOW; an explicit list (even empty) replaces it."""
    if values is None:
        configured = os.environ.get('LDRAW_SHADOW')
        values = configured.split(os.pathsep) if configured else []
    result = []
    for value in values:
        if not value:
            continue
        path = Path(value).expanduser().resolve()
        if not path.exists():
            raise ConfigError(f'LDCad shadow library missing at {path}')
        if path.is_dir() and not any((path / name).is_dir() for name in ('parts', 'p')):
            raise ConfigError(f'Shadow directory must contain parts/ or p/: {path}')
        if path.is_file() and not zipfile.is_zipfile(path):
            raise ConfigError(f'Shadow archive must be a ZIP or CSL: {path}')
        if path not in result:
            result.append(path)
    return result


def _leocad(value):
    candidate = value or os.environ.get('LEOCAD')
    if candidate:
        path = Path(candidate).expanduser()
        found = shutil.which(str(path))
        if not found:
            raise ConfigError(f'LeoCAD executable not found: {candidate}')
        return Path(found)
    found = shutil.which('leocad')
    if found:
        return Path(found)
    return MAC_LEOCAD if MAC_LEOCAD.is_file() else None


def _cache(value):
    path = value or os.environ.get('LDRAW_XRAY_CACHE')
    if path:
        return Path(path).expanduser().resolve()
    import platformdirs
    return Path(platformdirs.user_cache_dir('ldraw-xray'))


@dataclass(frozen=True)
class XrayConfig:
    """Resolved paths. Build it with `XrayConfig.resolve(...)` or `XrayConfig.from_env()`."""

    ldraw_lib: Path
    shadows: tuple[Path, ...] = ()
    leocad: Path | None = None
    cache_dir: Path = field(default_factory=lambda: _cache(None))

    @classmethod
    def resolve(cls, ldraw_lib=None, shadows=None, leocad=None, cache_dir=None, *, no_shadow=False):
        return cls(ldraw_lib=_library(ldraw_lib), shadows=() if no_shadow else tuple(_shadows(shadows)),
                   leocad=_leocad(leocad), cache_dir=_cache(cache_dir))

    @classmethod
    def from_env(cls):
        return cls.resolve()

    def require_leocad(self):
        if self.leocad is None:
            raise ConfigError('LeoCAD not found: install it, put `leocad` on PATH, set LEOCAD, or pass --leocad')
        return self.leocad


def discover(*, library=None, shadows=None, leocad=None, cache_dir=None, no_shadow=False):
    """Inspect each setting independently, including an incomplete installation."""
    found, errors = {}, {}
    checks = {
        'library': lambda: _library(library),
        'shadows': lambda: [] if no_shadow else _shadows(shadows),
        'leocad': lambda: _leocad(leocad),
        'cache_dir': lambda: _cache(cache_dir),
    }
    for name, check in checks.items():
        try:
            found[name] = check()
        except (ConfigError, OSError) as error:
            found[name] = None
            errors[name] = str(error)
    if found['leocad'] is None and 'leocad' not in errors:
        errors['leocad'] = 'LeoCAD not found; install it or set LEOCAD'
    return found, errors
