"""Selections of placements, written as short strings agents can compose.

Terms (case-insensitive):
  all                      every placement
  line:12,15,20-24         source line numbers of the placements
  step:3  step:3-5         source steps (1-based, counting every 0 STEP)
  part:3001*  part:30?9    glob on the referenced file name (".dat" optional)
  colour:15,4              colour codes as written on the placement line
  ref:NAME                 exact reference name (a child submodel or a part)
  section                  placements of the inspected section (in a parent context)

Combine with `|` (union); prefix a term with `!` to exclude it. A selection of
only exclusions starts from `all`. Example: `colour:15|part:3062*|!step:1`.
"""
from __future__ import annotations

import fnmatch

from .mpd import key


def _numbers(text):
    out = set()
    for chunk in text.split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        if '-' in chunk[1:]:
            a, b = chunk.split('-', 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(chunk))
    return out


def _term(term, placements, section):
    name, _, arg = term.partition(':')
    name = name.strip().casefold()
    if name == 'all':
        return set(range(len(placements)))
    if name == 'section':
        if not section:
            raise ValueError("'section' needs a scene with an inspected section")
        return {i for i, p in enumerate(placements) if key(p.ref) == key(section)}
    if not arg:
        raise ValueError(f'Selection term {term!r} needs a value, e.g. {name}:...')
    if name == 'line':
        wanted = _numbers(arg)
        return {i for i, p in enumerate(placements) if p.line in wanted}
    if name == 'step':
        wanted = _numbers(arg)
        return {i for i, p in enumerate(placements) if p.step in wanted}
    if name == 'colour' or name == 'color':
        wanted = {c.strip() for c in arg.split(',')}
        return {i for i, p in enumerate(placements) if p.colour in wanted}
    if name == 'part':
        patterns = [a.strip().casefold() for a in arg.split(',')]
        def match(ref):
            r = key(ref)
            return any(fnmatch.fnmatchcase(r, pat) or fnmatch.fnmatchcase(r.removesuffix('.dat'), pat) for pat in patterns)
        return {i for i, p in enumerate(placements) if match(p.ref)}
    if name == 'ref':
        return {i for i, p in enumerate(placements) if key(p.ref) == key(arg)}
    raise ValueError(f'Unknown selection term {term!r}; see ldraw_xray.select')


def select(spec, placements, *, section=None):
    """Indices of `placements` chosen by `spec` (a string; None means all)."""
    if spec is None or str(spec).strip() == '':
        return set(range(len(placements)))
    include, exclude = set(), set()
    terms = [t.strip() for t in str(spec).split('|') if t.strip()]
    positives = [t for t in terms if not t.startswith('!')]
    for t in positives:
        include |= _term(t, placements, section)
    for t in terms:
        if t.startswith('!'):
            exclude |= _term(t[1:], placements, section)
    if not positives:
        include = set(range(len(placements)))
    return include - exclude
