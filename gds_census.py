#!/usr/bin/env python3
"""
gds_census.py - architecture census + datapath regularity mining for a GDSII layout.

Assumes cell names survived (e.g. sky130_fd_sc_hd__nand2_1). Extracts NO geometry
beyond bounding boxes -- this is pure placement analysis.

Usage:
    python3 gds_census.py puzzle.gds
    python3 gds_census.py puzzle.gds --rows          # print every row string
    python3 gds_census.py puzzle.gds --cell INTERNAL_3
"""

import struct
import sys
from collections import Counter, defaultdict

REC = {
    0x02: 'LIBNAME', 0x03: 'UNITS', 0x05: 'BGNSTR', 0x06: 'STRNAME',
    0x07: 'ENDSTR', 0x08: 'BOUNDARY', 0x09: 'PATH', 0x0A: 'SREF',
    0x0B: 'AREF', 0x0C: 'TEXT', 0x0D: 'LAYER', 0x0E: 'DATATYPE',
    0x10: 'XY', 0x11: 'ENDEL', 0x12: 'SNAME', 0x13: 'COLROW',
    0x16: 'TEXTTYPE', 0x19: 'STRING', 0x1A: 'STRANS', 0x1C: 'ANGLE',
}

LIB = 'sky130_fd_sc_hd__'

# cells that carry no logic and should be ignored in structural analysis
NOISE_PREFIX = ('fill', 'decap', 'tap', 'diode', 'conb')


def gds_real(b):
    sign = -1.0 if b[0] & 0x80 else 1.0
    return sign * (int.from_bytes(b[1:8], 'big') / float(1 << 56)) * (16.0 ** ((b[0] & 0x7F) - 64))


def records(path):
    with open(path, 'rb') as f:
        while True:
            h = f.read(4)
            if len(h) < 4:
                return
            n = struct.unpack('>H', h[:2])[0]
            if n < 4:
                return
            yield h[2], h[3], f.read(n - 4)


def txt(d):
    return d.rstrip(b'\x00').decode('ascii', 'replace')


def i16(d):
    return struct.unpack('>h', d[:2])[0]


def xy(d):
    return [struct.unpack('>ii', d[i:i + 8]) for i in range(0, len(d) - 7, 8)]


def short(name):
    """sky130_fd_sc_hd__nand2_1 -> nand2_1 ; leave other names alone."""
    return name[len(LIB):] if name.startswith(LIB) else name


def is_noise(name):
    s = short(name)
    return s.startswith(NOISE_PREFIX) or s.startswith('VIA')


# ----------------------------------------------------------------- parsing

class Cell:
    __slots__ = ('name', 'srefs', 'texts', 'shapes', 'bbox')

    def __init__(self, name):
        self.name = name
        self.srefs = []      # (sname, x, y, angle, reflect)
        self.texts = []      # (layer, texttype, string, x, y)
        self.shapes = Counter()
        self.bbox = None

    def grow(self, pts):
        for x, y in pts:
            if self.bbox is None:
                self.bbox = [x, y, x, y]
            else:
                b = self.bbox
                if x < b[0]: b[0] = x
                if y < b[1]: b[1] = y
                if x > b[2]: b[2] = x
                if y > b[3]: b[3] = y


def parse(path):
    cells, cur = {}, None
    elem = layer = dtype = sname = None
    pts, strans, angle, string = [], 0, 0.0, None
    units = (1e-3, 1e-9)

    for rt, dt, data in records(path):
        r = REC.get(rt)
        if r == 'UNITS' and len(data) >= 16:
            units = (gds_real(data[0:8]), gds_real(data[8:16]))
        elif r == 'STRNAME':
            cur = Cell(txt(data))
            cells[cur.name] = cur
        elif r in ('BOUNDARY', 'PATH', 'SREF', 'AREF', 'TEXT'):
            elem = r
            layer = dtype = sname = string = None
            pts, strans, angle = [], 0, 0.0
        elif r == 'LAYER':
            layer = i16(data)
        elif r in ('DATATYPE', 'TEXTTYPE'):
            dtype = i16(data)
        elif r == 'SNAME':
            sname = txt(data)
        elif r == 'STRANS':
            strans = struct.unpack('>H', data[:2])[0]
        elif r == 'ANGLE':
            angle = gds_real(data[:8])
        elif r == 'STRING':
            string = txt(data)
        elif r == 'XY':
            pts = xy(data)
        elif r == 'ENDEL' and cur is not None:
            if elem in ('BOUNDARY', 'PATH') and layer is not None:
                cur.shapes[(layer, dtype)] += 1
                cur.grow(pts)
            elif elem in ('SREF', 'AREF') and sname and pts:
                cur.srefs.append((sname, pts[0][0], pts[0][1],
                                  int(angle) % 360, bool(strans & 0x8000)))
            elif elem == 'TEXT' and string is not None and pts:
                cur.texts.append((layer, dtype, string, pts[0][0], pts[0][1]))
            elem = None
    return cells, units


# ------------------------------------------------------------- analysis

def effective_counts(cells, top):
    """Total instances of every leaf cell, expanding the hierarchy."""
    total = Counter()
    stack = [(top, 1)]
    while stack:
        name, mult = stack.pop()
        c = cells.get(name)
        if c is None or not c.srefs:
            continue
        for sname, *_ in c.srefs:
            total[sname] += mult
            if cells.get(sname) and cells[sname].srefs:
                stack.append((sname, mult))
    return total


def flatten(cells, top):
    """Expand the hierarchy into absolute leaf placements."""
    import math
    out = []
    stack = [(top, 0, 0, 0, False)]
    while stack:
        name, x0, y0, ang, refl = stack.pop()
        c = cells.get(name)
        if c is None:
            continue
        a = math.radians(ang)
        ca, sa = math.cos(a), math.sin(a)
        for sname, x, y, sang, srefl in c.srefs:
            yy = -y if refl else y
            ax = int(round(x * ca - yy * sa)) + x0
            ay = int(round(x * sa + yy * ca)) + y0
            nang = (ang - sang if refl else ang + sang) % 360
            nrefl = refl ^ srefl
            if cells.get(sname) and cells[sname].srefs:
                stack.append((sname, ax, ay, nang, nrefl))
            else:
                out.append((sname, ax, ay, nang, nrefl))
    return out


def row_strings(placements, tol=100):
    """Group absolute placements into rows by y, sorted left to right."""
    rows = defaultdict(list)
    for sname, x, y, ang, refl in placements:
        if short(sname).startswith('VIA'):
            continue
        rows[y].append((x, sname))
    out = []
    for y in sorted(rows):
        seq = [short(s) for _, s in sorted(rows[y])]
        out.append((y, seq))
    return out


def primitive(gram):
    """Smallest motif m such that gram is m repeated (m itself if none)."""
    n = len(gram)
    for p in range(1, n + 1):
        if n % p == 0 and all(gram[i] == gram[i % p] for i in range(n)):
            return gram[:p]
    return gram


def canonical(motif):
    """Rotation-invariant form, so ABCD and BCDA are recognised as the same."""
    return min(tuple(motif[i:] + motif[:i]) for i in range(len(motif)))


def ngram_repeats(rows, lo=2, hi=16, keep=10):
    """Find the primitive repeating motifs (bitslices) and count occurrences."""
    cleaned = [[s for s in seq if not s.startswith(NOISE_PREFIX)] for _, seq in rows]

    grams = Counter()
    for clean in cleaned:
        for n in range(lo, hi + 1):
            for i in range(len(clean) - n + 1):
                grams[tuple(clean[i:i + n])] += 1

    motifs = {}
    for g, c in grams.items():
        if c < 3:
            continue
        m = primitive(g)
        if len(m) == len(g) and len(g) > lo:
            continue          # not actually periodic; keep only real motifs
        motifs.setdefault(canonical(m), m)

    scored = []
    for key, m in motifs.items():
        hits, n = 0, len(m)
        for clean in cleaned:
            i = 0
            while i <= len(clean) - n:
                if tuple(clean[i:i + n]) == tuple(m):
                    hits += 1
                    i += n            # non-overlapping
                else:
                    i += 1
        if hits >= 3:
            scored.append((m, hits, hits * n))
    scored.sort(key=lambda t: (-t[2], len(t[0])))
    return scored[:keep]


# --------------------------------------------------------------- report

def main(path, show_rows=False, focus=None):
    cells, units = parse(path)
    nm = units[1] * 1e9

    referenced = {s for c in cells.values() for s, *_ in c.srefs}
    tops = [n for n in cells if n not in referenced and cells[n].srefs]
    tops.sort(key=lambda n: -len(cells[n].srefs))
    top = focus or (tops[0] if tops else max(cells, key=lambda n: len(cells[n].srefs)))
    if len(tops) > 1:
        print(f'note: {len(tops)} unreferenced cells with placements: {tops}')

    print('=' * 72)
    print(f'{path}   1 DB unit = {nm:g} nm   top cell = {top}')
    print('=' * 72)

    print('\n--- HIERARCHY ---')
    for name in sorted(cells):
        c = cells[name]
        kids = Counter(s for s, *_ in c.srefs)
        if not kids:
            continue
        blocks = {k: v for k, v in kids.items()
                  if cells.get(k) and cells[k].srefs}
        leaves = sum(v for k, v in kids.items() if k not in blocks)
        print(f'  {name}: {leaves:,} leaf placements'
              + (f'  + sub-blocks {dict(blocks)}' if blocks else ''))

    counts = effective_counts(cells, top)
    logic = Counter({k: v for k, v in counts.items() if not is_noise(k)})
    noise = Counter({k: v for k, v in counts.items() if is_noise(k)})

    print(f'\n--- CELL CENSUS ---   {sum(logic.values()):,} logic, '
          f'{sum(noise.values()):,} filler/via')
    for name, n in logic.most_common():
        print(f'  {n:>7,}  {short(name)}')

    ff = sum(v for k, v in logic.items()
             if short(k).startswith(('df', 'dl', 'sdf', 'edf')))
    arith = sum(v for k, v in logic.items()
                if short(k).startswith(('fa', 'ha', 'maj3', 'xor', 'xnor')))
    print(f'\n  state elements (flip-flops/latches): {ff:,}   <- design state bits')
    print(f'  adder-ish cells (fa/ha/maj3/xor/xnor): {arith:,}')

    print('\n--- LABELS BY CELL ---')
    for name in sorted(cells):
        c = cells[name]
        if not c.texts:
            continue
        vals = sorted({t[2] for t in c.texts})
        kind = 'PIN NAMES' if name.startswith(LIB) else 'NET / PORT NAMES'
        print(f'  {name}  ({len(c.texts)} labels, {kind})')
        for v in vals[:40]:
            print(f'      {v}')
        if len(vals) > 40:
            print(f'      ... and {len(vals) - 40} more distinct')

    placements = flatten(cells, top)
    rows = row_strings(placements)
    print(f'\n--- ROW STRUCTURE (hierarchy flattened) ---   '
          f'{len(placements):,} placements in {len(rows)} rows')
    if rows:
        ys = [y for y, _ in rows]
        pitches = sorted({ys[i + 1] - ys[i] for i in range(len(ys) - 1)})
        print(f'  row y-pitch(es): {pitches[:6]}  ({pitches[0] * nm:g} nm '
              f'= {pitches[0] * nm / 1000:g} um if uniform)')
        xs = sorted({x for s, x, y, a, r in placements})
        d = sorted({xs[i + 1] - xs[i] for i in range(len(xs) - 1)})
        print(f'  smallest x-steps: {d[:6]}  (site width candidate)')

    print('\n--- REPEATED CELL PATTERNS (bitslice candidates) ---')
    for gram, count, cover in ngram_repeats(rows):
        print(f'  x{count:<4} len {len(gram):<3}  ' + ' '.join(gram))

    if show_rows:
        print('\n--- FULL ROW STRINGS ---')
        for y, seq in rows:
            print(f'\n  y={y}  ({len(seq)} cells)')
            print('    ' + ' '.join(seq))
    print('=' * 72)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]
    if not args:
        print(__doc__)
        sys.exit(1)
    focus = None
    for i, a in enumerate(sys.argv):
        if a == '--cell' and i + 1 < len(sys.argv):
            focus = sys.argv[i + 1]
            args = [x for x in args if x != focus]
    main(args[0], show_rows='--rows' in flags, focus=focus)
