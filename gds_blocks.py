#!/usr/bin/env python3
"""
gds_blocks.py - floorplan geography + per-module census for a hierarchical GDSII.

Answers three questions:
  1. Where are the repeated sub-blocks physically placed? (architecture hint)
  2. How much logic and state lives in each module?
  3. Where do the top-level ports enter the die?

Usage:
    python3 gds_blocks.py puzzle.gds
    python3 gds_blocks.py puzzle.gds --grid 40      # wider ASCII map
"""

import struct
import sys
from collections import Counter, defaultdict

REC = {0x03: 'UNITS', 0x06: 'STRNAME', 0x08: 'BOUNDARY', 0x09: 'PATH',
       0x0A: 'SREF', 0x0B: 'AREF', 0x0C: 'TEXT', 0x0D: 'LAYER',
       0x0E: 'DATATYPE', 0x10: 'XY', 0x11: 'ENDEL', 0x12: 'SNAME',
       0x16: 'TEXTTYPE', 0x19: 'STRING', 0x1A: 'STRANS', 0x1C: 'ANGLE'}

LIB = 'sky130_fd_sc_hd__'
NOISE = ('fill', 'decap', 'tap', 'diode', 'conb')
FLOP = ('df', 'dl', 'sdf', 'edf')


def gds_real(b):
    s = -1.0 if b[0] & 0x80 else 1.0
    return s * (int.from_bytes(b[1:8], 'big') / float(1 << 56)) * 16.0 ** ((b[0] & 0x7F) - 64)


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


def short(n):
    return n[len(LIB):] if n.startswith(LIB) else n


def parse(path):
    cells, cur = {}, None
    elem = layer = dtype = sname = string = None
    pts, strans, angle = [], 0, 0.0
    units = (1e-3, 1e-9)
    for rt, dt, data in records(path):
        r = REC.get(rt)
        if r == 'UNITS' and len(data) >= 16:
            units = (gds_real(data[:8]), gds_real(data[8:16]))
        elif r == 'STRNAME':
            cur = data.rstrip(b'\x00').decode('ascii', 'replace')
            cells[cur] = {'srefs': [], 'texts': [], 'bbox': None, 'shapes': Counter()}
        elif r in ('BOUNDARY', 'PATH', 'SREF', 'AREF', 'TEXT'):
            elem, layer, dtype, sname, string = r, None, None, None, None
            pts, strans, angle = [], 0, 0.0
        elif r == 'LAYER':
            layer = struct.unpack('>h', data[:2])[0]
        elif r in ('DATATYPE', 'TEXTTYPE'):
            dtype = struct.unpack('>h', data[:2])[0]
        elif r == 'SNAME':
            sname = data.rstrip(b'\x00').decode('ascii', 'replace')
        elif r == 'STRANS':
            strans = struct.unpack('>H', data[:2])[0]
        elif r == 'ANGLE':
            angle = gds_real(data[:8])
        elif r == 'STRING':
            string = data.rstrip(b'\x00').decode('ascii', 'replace')
        elif r == 'XY':
            pts = [struct.unpack('>ii', data[i:i + 8]) for i in range(0, len(data) - 7, 8)]
        elif r == 'ENDEL' and cur:
            c = cells[cur]
            if elem in ('BOUNDARY', 'PATH') and layer is not None:
                c['shapes'][(layer, dtype)] += 1
                for x, y in pts:
                    b = c['bbox']
                    c['bbox'] = [x, y, x, y] if b is None else \
                        [min(b[0], x), min(b[1], y), max(b[2], x), max(b[3], y)]
            elif elem in ('SREF', 'AREF') and sname and pts:
                c['srefs'].append((sname, pts[0][0], pts[0][1],
                                   int(angle) % 360, bool(strans & 0x8000)))
            elif elem == 'TEXT' and string is not None and pts:
                c['texts'].append((layer, dtype, string, pts[0][0], pts[0][1]))
            elem = None
    return cells, units


def ascii_map(points, labels, cols=60):
    """Render (x, y, char) points as an ASCII scatter, y increasing upward."""
    if not points:
        return ['(none)']
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w = max(x1 - x0, 1)
    h = max(y1 - y0, 1)
    rows = max(3, min(30, int(cols * h / w / 2) + 1))
    grid = [[' '] * cols for _ in range(rows)]
    for (x, y, ch) in points:
        cx = int((x - x0) / w * (cols - 1))
        cy = int((y - y0) / h * (rows - 1))
        grid[rows - 1 - cy][cx] = ch
    out = ['  +' + '-' * cols + '+']
    for row in grid:
        out.append('  |' + ''.join(row) + '|')
    out.append('  +' + '-' * cols + '+')
    out.append('  legend: ' + '  '.join(f'{c}={n}' for c, n in labels))
    return out


def main(path, cols=60):
    cells, units = parse(path)
    nm = units[1] * 1e9
    referenced = {s for c in cells.values() for s, *_ in c['srefs']}
    tops = [n for n in cells if n not in referenced and cells[n]['srefs']]
    top = max(tops, key=lambda n: len(cells[n]['srefs'])) if tops else None
    blocks = [n for n in cells if cells[n]['srefs'] and n != top]

    print('=' * 74)
    print(f'{path}   1 DBU = {nm:g} nm   top = {top}')
    print('=' * 74)

    # ---- per-module census -------------------------------------------------
    print('\n### PER-MODULE CENSUS  (cells written directly in each module)\n')
    per = {}
    for name in [top] + sorted(blocks):
        c = cells[name]
        kinds = Counter(short(s) for s, *_ in c['srefs'])
        logic = Counter({k: v for k, v in kinds.items()
                         if not k.startswith(NOISE) and not k.startswith('VIA')
                         and k not in cells})
        subs = Counter({k: v for k, v in kinds.items() if k in cells})
        flops = sum(v for k, v in logic.items() if k.startswith(FLOP))
        per[name] = (logic, subs, flops)
        bb = c['bbox']
        size = f'{(bb[2]-bb[0])*nm/1000:.1f} x {(bb[3]-bb[1])*nm/1000:.1f} um' if bb else '?'
        print(f'  {name}   [{size}]')
        print(f'    logic cells: {sum(logic.values()):>5}    flip-flops: {flops:>4}')
        if subs:
            print(f'    sub-blocks : {dict(subs)}')
        print('    ' + ', '.join(f'{k}x{v}' for k, v in logic.most_common(14)))
        if len(logic) > 14:
            print(f'    ... {len(logic)-14} more types')
        print()

    # ---- effective totals --------------------------------------------------
    mult = Counter({top: 1})
    stack = [(top, 1)]
    while stack:
        n, m = stack.pop()
        for s, *_ in cells[n]['srefs']:
            if s in cells and cells[s]['srefs']:
                mult[s] += m
                stack.append((s, m))
    tot_logic, tot_flops = Counter(), 0
    for name, (logic, subs, flops) in per.items():
        m = mult.get(name, 0)
        tot_flops += flops * m
        for k, v in logic.items():
            tot_logic[k] += v * m
    print(f'### EFFECTIVE TOTALS (hierarchy expanded)')
    print(f'  module multiplicities: {dict(mult)}')
    print(f'  total logic cells : {sum(tot_logic.values()):,}')
    print(f'  TOTAL STATE BITS  : {tot_flops:,}   <-- size of the machine\n')
    for k, v in tot_logic.most_common(25):
        print(f'    {v:>6,}  {k}')

    # ---- floorplan ---------------------------------------------------------
    print(f'\n### BLOCK FLOORPLAN inside {top}\n')
    chars, pts, legend = {}, [], []
    for i, b in enumerate(sorted(blocks)):
        ch = str(i + 3) if i < 7 else chr(ord('a') + i)
        chars[b] = ch
        legend.append((ch, b))
    for sname, x, y, ang, refl in cells[top]['srefs']:
        if sname in chars:
            pts.append((x, y, chars[sname]))
    for line in ascii_map(pts, legend, cols):
        print(line)

    for b in sorted(blocks):
        inst = [(x, y, ang, refl) for s, x, y, ang, refl
                in cells[top]['srefs'] if s == b]
        if not inst:
            continue
        xs = sorted({x for x, y, a, r in inst})
        ys = sorted({y for x, y, a, r in inst})
        print(f'\n  {b}: {len(inst)} instances')
        print(f'    distinct X ({len(xs)}): {[round(v*nm/1000,1) for v in xs]}')
        print(f'    distinct Y ({len(ys)}): {[round(v*nm/1000,1) for v in ys]}')
        print(f'    orientations: {Counter((a, r) for x, y, a, r in inst)}')
        print('    placements (um):')
        for x, y, a, r in sorted(inst, key=lambda t: (-t[1], t[0])):
            print(f'      ({x*nm/1000:8.2f}, {y*nm/1000:8.2f})  rot={a:<4} mirror={r}')

    # ---- ports -------------------------------------------------------------
    print(f'\n### TOP-LEVEL PORTS (text labels in {top})\n')
    for layer, dtype, s, x, y in sorted(cells[top]['texts'], key=lambda t: t[2]):
        print(f'  {s:<12} layer {layer}/{dtype}   at ({x*nm/1000:9.2f}, {y*nm/1000:9.2f}) um')
    print('=' * 74)


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    cols = 60
    for i, x in enumerate(sys.argv):
        if x == '--grid' and i + 1 < len(sys.argv):
            cols = int(sys.argv[i + 1])
            a = [z for z in a if z != sys.argv[i + 1]]
    if not a:
        print(__doc__)
        sys.exit(1)
    main(a[0], cols)
