"""Read-only views of the LDraw library: a pyldraw3 index and a LeoCAD render library.

The installed library is never written. pyldraw3 gets a `parts.lst` built in the
cache. LeoCAD gets a wrapper directory: symlinks to the real library, an
`LDConfig.ldr` extended with the xray palette, and an `unofficial/parts/` folder
holding embedded and synthetic DAT files (LeoCAD's MPD loader treats embedded
DAT blocks as model content and can drop them, so they are materialized).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import NamedTemporaryFile

from .config import XrayConfig
from .mpd import Document, key
from .palette import ldconfig_lines


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with NamedTemporaryFile('w', encoding='utf-8', newline='', dir=path.parent, delete=False) as f:
            tmp = Path(f.name)
            f.write(text)
        tmp.replace(path)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)


def _ldconfig(root):
    return next(p for p in root.iterdir() if p.name.casefold() == 'ldconfig.ldr')


def parts_index(config: XrayConfig):
    """pyldraw3 `Parts` over a cached read-through view, with shadow libraries attached."""
    from ldraw import Parts

    root = config.ldraw_lib
    target = config.cache_dir / ('library-' + hashlib.sha256(str(root).encode()).hexdigest()[:12])
    target.mkdir(parents=True, exist_ok=True)
    for entry in root.iterdir():
        if entry.name.casefold() in {'parts', 'p', 'ldconfig.ldr'}:
            link = target / entry.name
            if not link.is_symlink():
                link.symlink_to(entry, target_is_directory=entry.is_dir())
    files = sorted((root / 'parts').glob('*.dat'))
    signature = hashlib.sha256('\n'.join(f'{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}' for p in files).encode()).hexdigest()
    stamp, index = target / 'signature', target / 'parts.lst'
    if not index.exists() or not stamp.exists() or stamp.read_text() != signature:
        rows = []
        for p in files:
            with p.open(encoding='utf-8-sig', errors='replace') as f:
                rows.append(f'{p.name} ' + next(f, '0').strip().removeprefix('0').strip())
        atomic_write(index, '\n'.join(rows) + '\n')
        atomic_write(stamp, signature)
    parts = Parts(index)
    for source in config.shadows:
        parts.add_connection_shadow(source)
    return parts


def _link_tree(source: Path, target: Path):
    """Real directory `target` whose entries are symlinks to `source`'s entries."""
    target.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        link = target / entry.name
        if not link.exists() and not link.is_symlink():
            link.symlink_to(entry.resolve(), target_is_directory=entry.is_dir())


def render_library(config: XrayConfig, doc: Document, temp: Path):
    """Write `doc` as a LeoCAD-ready MPD plus its wrapper library.

    Returns (mpd_path, library_path, renamed) where `renamed` maps the original
    names of materialized DAT blocks to their wrapper file names.
    """
    temp = Path(temp)
    root = config.ldraw_lib
    lib = temp / 'library'
    lib.mkdir()
    unofficial = lib / 'unofficial'
    for entry in root.iterdir():
        name = entry.name.casefold()
        if name == 'ldconfig.ldr':
            continue
        if name == 'unofficial' and entry.is_dir():
            unofficial.mkdir(exist_ok=True)
            for sub in entry.iterdir():
                if sub.is_dir() and sub.name.casefold() == 'parts':
                    _link_tree(sub, unofficial / 'parts')
                else:
                    (unofficial / sub.name).symlink_to(sub.resolve(), target_is_directory=sub.is_dir())
            continue
        (lib / entry.name).symlink_to(entry.resolve(), target_is_directory=entry.is_dir())
    base = _ldconfig(root).read_text(encoding='utf-8-sig', errors='replace').rstrip('\r\n')
    atomic_write(lib / 'LDConfig.ldr', base + '\n' + '\n'.join(ldconfig_lines()) + '\n')

    doc = doc.copy()
    embedded = [k for k in doc.order if doc.blocks[k].is_part]
    digest = hashlib.sha256(doc.text().encode()).hexdigest()[:12]
    renamed = {k: f'xray-{digest}-{i:03d}.dat' for i, k in enumerate(embedded)}

    def rewrite(lines):
        out = []
        for raw in lines:
            t = raw.strip().split(None, 14)
            if len(t) == 15 and t[0] == '1' and key(t[14]) in renamed:
                raw = ' '.join(t[:14]) + ' ' + renamed[key(t[14])]
            out.append(raw)
        return out

    if embedded:
        (unofficial / 'parts').mkdir(parents=True, exist_ok=True)
    for k in embedded:
        block = doc.blocks.pop(k)
        doc.order.remove(k)
        body = [('0 Name: ' + renamed[k]) if l.strip().startswith('0 Name:') else l for l in rewrite(block.lines)]
        atomic_write(unofficial / 'parts' / renamed[k], '\r\n'.join(body) + '\r\n')
    for b in doc.blocks.values():
        b.lines = rewrite(b.lines)
    if not doc.order:
        raise ValueError('Nothing to render: the document only contains part definitions')
    mpd = temp / 'xray-render.mpd'
    atomic_write(mpd, doc.text())
    return mpd, lib, renamed
