"""Provenance written next to every board or render folder."""
from __future__ import annotations

import hashlib
import platform
from importlib import metadata
from pathlib import Path

from .mpd import Document


def versions(config=None):
    from .leocad import version
    out = dict(ldraw_xray=_version('ldraw-xray'), pyldraw3=_version('pyldraw3'), python=platform.python_version())
    if config is not None and config.leocad:
        out['leocad'] = version(config.leocad)
    return out


def _version(dist):
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None


def source_info(path, section):
    """Identity of the inspected section: hash, steps, parents and their placement lines."""
    path = Path(path).resolve()
    doc = Document.read(path)
    block = doc.block(section)
    parents = {name: [p.text() for p in hits] for name, hits in doc.parents_of(block.name).items()}
    return dict(source=str(path), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), section=block.name,
                section_first_line=block.first_line, steps=block.step_count(),
                empty_leading_steps=block.empty_leading_steps(), parents=parents)


def section_text(path, section):
    block = Document.read(path).block(section)
    return '0 FILE ' + block.name + '\n' + '\n'.join(block.lines) + '\n0 NOFILE\n'
