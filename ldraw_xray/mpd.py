"""Line-preserving MPD/LDR documents for building synthetic inspection copies.

pyldraw3 does the geometry; this module keeps the source text intact so copies
differ from the original only where a layer changed something. Line numbers are
1-based source-file lines, the same numbers editors and other tools show.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

STEP_META = ('0 STEP', '0 ROTSTEP')


def key(name):
    """Case- and separator-insensitive identity of a FILE block or reference."""
    return name.strip().replace('\\', '/').casefold()


def is_part_name(name):
    return key(name).endswith('.dat')


def _num(value):
    return '0' if abs(value) < 1e-9 else f'{value:.6g}'


@dataclass(frozen=True)
class Placement:
    """One type-1 line, or a leaf derived from one by flattening children."""

    colour: str
    pos: np.ndarray
    matrix: np.ndarray
    ref: str
    line: int | None = None            # source line of the placement in its block
    step: int = 1                      # 1-based step inside the block it is emitted into
    origin: tuple[int | None, ...] = ()  # source lines from the subject block down to this leaf
    final: bool = False                # emitted into the synthetic final (highlight) step

    @classmethod
    def parse(cls, text, line=None, step=1):
        t = text.split(None, 14)
        if len(t) != 15 or t[0] != '1':
            return None
        v = [float(x) for x in t[2:14]]
        return cls(t[1], np.array(v[:3]), np.array(v[3:]).reshape(3, 3), t[14].strip(), line, step, (line,))

    def text(self):
        nums = [*self.pos, *self.matrix.reshape(-1)]
        return '1 ' + self.colour + ' ' + ' '.join(_num(v) for v in nums) + ' ' + self.ref

    def moved(self, **changes):
        return replace(self, **changes)


@dataclass
class Block:
    name: str
    lines: list[str]                   # raw lines after `0 FILE`, before `0 NOFILE`
    first_line: int = 1                # source line number of lines[0]

    @property
    def is_part(self):
        return is_part_name(self.name)

    def placements(self):
        step, result = 1, []
        for offset, raw in enumerate(self.lines):
            s = raw.strip()
            if s.upper().startswith(STEP_META):
                step += 1
                continue
            p = Placement.parse(s, self.first_line + offset, step)
            if p:
                result.append(p)
        return result

    def header(self):
        """Leading meta/comment lines up to the first placement or step."""
        out = []
        for raw in self.lines:
            s = raw.strip()
            if s.startswith('1 ') or s.upper().startswith(STEP_META):
                break
            out.append(raw)
        return out

    def step_count(self):
        """Source steps, counting a trailing step without `0 STEP` but not empty leading ones."""
        steps = [p.step for p in self.placements()]
        return max(steps) if steps else 0

    def empty_leading_steps(self):
        steps = [p.step for p in self.placements()]
        return (min(steps) - 1) if steps else 0


@dataclass
class Document:
    path: Path | None
    blocks: dict[str, Block] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    multipart: bool = True

    @classmethod
    def read(cls, path):
        path = Path(path)
        return cls.parse(path.read_text(encoding='utf-8-sig', errors='replace'), path)

    @classmethod
    def parse(cls, text, path=None):
        doc, current = cls(Path(path) if path else None), None
        lines = text.splitlines()
        for number, raw in enumerate(lines, 1):
            s = raw.strip()
            fields = s.split(None, 2)
            if fields[:2] == ['0', 'FILE'] and len(fields) == 3:
                name = fields[2].strip()
                if key(name) in doc.blocks:
                    raise ValueError(f'Duplicate FILE block {name!r}')
                current = Block(name, [], number + 1)
                doc.blocks[key(name)] = current
                doc.order.append(key(name))
            elif fields[:2] == ['0', 'NOFILE']:
                current = None
            elif current is not None:
                current.lines.append(raw.rstrip('\r'))
        if not doc.blocks:
            name = Path(path).name if path else 'model.ldr'
            doc.blocks[key(name)] = Block(name, [l.rstrip('\r') for l in lines], 1)
            doc.order.append(key(name))
            doc.multipart = False
        return doc

    @property
    def root(self):
        return self.blocks[self.order[0]]

    def block(self, name):
        try:
            return self.blocks[key(name)]
        except KeyError:
            raise KeyError(f'Section not found: {name!r}') from None

    def model_section(self, name=None):
        """Resolve an optional section name to a model block."""
        block = self.root if name is None else self.block(name)
        if block.is_part:
            raise ValueError(f'{block.name!r} is a part definition, not a model section')
        return block

    def parent_name(self, section, name=None, *, useful=False, required=True):
        """Resolve an explicit or unique parent, never silently choose among several."""
        parents = self.parents_of(section)
        if name is not None:
            block = self.model_section(name)
            if block.name not in parents:
                raise ValueError(f'{block.name!r} does not place {section!r}')
            return block.name
        candidates = [parent for parent, hits in parents.items()
                      if not useful or len(self.block(parent).placements()) > len(hits)]
        if len(candidates) > 1:
            raise ValueError(f'Multiple parents of {section!r}; choose --parent NAME: {", ".join(candidates)}')
        if not candidates:
            if required:
                raise ValueError(f'No parent places {section!r}; omit --parent to render it alone')
            return None
        return candidates[0]

    def is_model(self, ref):
        return key(ref) in self.blocks and not is_part_name(ref)

    def parents_of(self, name):
        """{parent block name: [placements of `name` in it]} in file order."""
        result = {}
        for k in self.order:
            hits = [p for p in self.blocks[k].placements() if key(p.ref) == key(name)]
            if hits:
                result[self.blocks[k].name] = hits
        return result

    def flatten(self, placement, depth=0):
        """Leaf placements of `placement`, transformed into its block's frame.

        Colour 16 inherits the placing colour, as in LDraw. Embedded `.dat` blocks
        are parts (leaves), not models.
        """
        if not self.is_model(placement.ref) or depth > 32:
            yield placement
            return
        for child in self.block(placement.ref).placements():
            colour = placement.colour if child.colour == '16' else child.colour
            leaf = child.moved(colour=colour, pos=placement.matrix @ child.pos + placement.pos,
                               matrix=placement.matrix @ child.matrix, line=placement.line, step=placement.step,
                               origin=placement.origin + (child.line,), final=placement.final)
            yield from self.flatten(leaf, depth + 1)

    def text(self):
        if not self.multipart:
            return '\n'.join(self.root.lines) + '\n'
        out = []
        for k in self.order:
            b = self.blocks[k]
            out += ['0 FILE ' + b.name, *b.lines, '0 NOFILE']
        return '\n'.join(out) + '\n'

    def copy(self):
        return Document(self.path, {k: Block(b.name, list(b.lines), b.first_line) for k, b in self.blocks.items()},
                        list(self.order), self.multipart)

    def add_block(self, name, lines):
        if key(name) in self.blocks:
            raise ValueError(f'Block {name!r} already exists')
        self.blocks[key(name)] = Block(name, list(lines), 0)
        self.order.append(key(name))
        self.multipart = True


def step_map(placements):
    """Source step -> rendered step. `emit` never writes empty steps, so the numbering
    LeoCAD uses for `--from/--to` is exactly this dense ranking."""
    return {s: i for i, s in enumerate(sorted({p.step for p in placements}), 1)}


def emit(header, placements, *, keep_steps):
    """Block lines from placements. keep_steps keeps the source steps (empty ones
    dropped, see `step_map`); otherwise one base step followed by a final step
    holding the `final` placements."""
    lines = list(header)
    if keep_steps:
        if any(p.final for p in placements):
            raise ValueError('Highlight/ghost layers cannot be combined with source-step rendering')
        current = None
        for p in sorted(placements, key=lambda p: p.step):
            if current is not None and p.step != current:
                lines.append('0 STEP')
            current = p.step
            lines.append(p.text())
        return lines + ['0 STEP']
    base = [p for p in placements if not p.final]
    final = [p for p in placements if p.final]
    lines += [p.text() for p in base]
    if final:
        lines += (['0 STEP'] if base else []) + [p.text() for p in final]
    return lines + ['0 STEP']
