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
import re

from .mpd import key


def numbers(text):
    """Positive source numbers, e.g. ``3,7-9``; reject malformed ranges."""
    if not isinstance(text, str) or not re.fullmatch(r'\s*\d+(?:\s*-\s*\d+)?(?:\s*,\s*\d+(?:\s*-\s*\d+)?)*\s*', text):
        raise ValueError('Expected source numbers such as 3,7-9')
    out = set()
    for chunk in text.split(','):
        chunk = chunk.strip()
        if '-' in chunk:
            a, b = chunk.split('-', 1)
            if int(a) < 1 or int(b) < int(a):
                raise ValueError(f'Invalid source range: {chunk!r}')
            out.update(range(int(a), int(b) + 1))
        else:
            value = int(chunk)
            if value < 1:
                raise ValueError('Source numbers start at 1')
            out.add(value)
    return out


def _term(term, placements, section):
    name, _, arg = term.partition(':')
    name = name.strip().casefold()
    if name in ('all', 'section') and ':' in term:
        raise ValueError(f'{name} does not take a value')
    if name == 'all':
        return set(range(len(placements)))
    if name == 'section':
        if not section:
            raise ValueError("'section' needs a scene with an inspected section")
        return {i for i, p in enumerate(placements) if key(p.ref) == key(section)}
    if not arg:
        raise ValueError(f'Selection term {term!r} needs a value, e.g. {name}:...')
    if name == 'line':
        wanted = numbers(arg)
        return {i for i, p in enumerate(placements) if p.line in wanted}
    if name == 'step':
        wanted = numbers(arg)
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
    if spec is None:
        return set(range(len(placements)))
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError('Selection must be nonempty text, such as all or step:3')
    include, exclude = set(), set()
    terms = [t.strip() for t in spec.split('|')]
    if not all(terms):
        raise ValueError('Selection has an empty term around |')
    positives = [t for t in terms if not t.startswith('!')]
    for t in positives:
        include |= _term(t, placements, section)
    for t in terms:
        if t.startswith('!'):
            exclude |= _term(t[1:], placements, section)
    if not positives:
        include = set(range(len(placements)))
    return include - exclude
