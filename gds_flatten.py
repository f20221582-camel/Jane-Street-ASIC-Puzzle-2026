#!/usr/bin/env python3
"""
gds_flatten.py - Phase 1 + 2 of the extraction pipeline.

Phase 1: read every shape, including PATH records, and give paths their real
         width (plus correct end extensions) so they become rectangles.
Phase 2: walk the hierarchy and place every shape at its true die position.

Writes a pickle containing:
    shapes    list of (layer, datatype, x1, y1, x2, y2, owner)
              owner = instance index, or -1 for top-level routing
    insts     list of (index, cellname, x, y, angle, mirror)
    cellpins  {cellname: [(pinname, layer, dt, x1, y1, x2, y2), ...]} local coords
    ports     list of (name, layer, dt, x, y) from the top cell
    dbu_nm    nanometres per database unit

Usage:
    python3 gds_flatten.py puzzle.gds
    python3 gds_flatten.py puzzle.gds --out puzzle_flat.pkl
"""

import pickle
import struct
import sys
from collections import Counter, defaultdict

REC = {0x03: 'UNITS', 0x06: 'STRNAME', 0x07: 'ENDSTR', 0x08: 'BOUNDARY',
       0x09: 'PATH', 0x0A: 'SREF', 0x0B: 'AREF', 0x0C: 'TEXT', 0x0D: 'LAYER',
       0x0E: 'DATATYPE', 0x0F: 'WIDTH', 0x10: 'XY', 0x11: 'ENDEL',
       0x12: 'SNAME', 0x13: 'COLROW', 0x16: 'TEXTTYPE', 0x19: 'STRING',
       0x1A: 'STRANS', 0x1B: 'MAG', 0x1C: 'ANGLE', 0x21: 'PATHTYPE',
       0x2D: 'BOX', 0x2E: 'BOXTYPE', 0x30: 'BGNEXTN', 0x31: 'ENDEXTN'}

# layers that carry current, or that we need for pin mapping
ROUTING = {(67, 20), (68, 20), (69, 20), (70, 20), (71, 20), (72, 20)}
CUTS    = {(66, 44), (67, 44), (68, 44), (69, 44), (70, 44), (71, 44)}
PINS    = {(67, 16), (68, 16), (69, 16), (70, 16), (71, 16), (72, 16)}
LABELS  = {(67, 5), (68, 5), (69, 5), (70, 5), (71, 5), (72, 5)}
KEEP    = ROUTING | CUTS | PINS

# what each cut layer bridges, lower first
CUT_BRIDGE = {
    (66, 44): ((66, 20), (67, 20)),   # licon1 : poly -> li1
    (67, 44): ((67, 20), (68, 20)),   # mcon   : li1  -> met1
    (68, 44): ((68, 20), (69, 20)),   # via    : met1 -> met2
    (69, 44): ((69, 20), (70, 20)),   # via2   : met2 -> met3
    (70, 44): ((70, 20), (71, 20)),   # via3   : met3 -> met4
    (71, 44): ((71, 20), (72, 20)),   # via4   : met4 -> met5
}


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


# ---------------------------------------------------------------- PHASE 1

def path_to_rects(pts, width, pathtype, bgnextn, endextn):
    """A PATH is a centreline plus a width. Turn it into solid rectangles.

    pathtype 0 = flush ends (default)
             1 = round cap, sticks out half a width
             2 = square cap, sticks out half a width
             4 = custom, use bgnextn / endextn
    """
    if width <= 0:
        width = 2
    hw = width // 2
    e0 = e1 = 0
    if pathtype in (1, 2):
        e0 = e1 = hw
    elif pathtype == 4:
        e0, e1 = bgnextn, endextn

    rects = []
    n = len(pts)
    if n == 1:
        x, y = pts[0]
        return [(x - hw, y - hw, x + hw, y + hw)]

    for i in range(n - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        a0 = e0 if i == 0 else 0
        a1 = e1 if i == n - 2 else 0
        if y0 == y1:                                   # horizontal segment
            lo, hi = (x0, x1) if x0 <= x1 else (x1, x0)
            if x0 <= x1:
                lo -= a0; hi += a1
            else:
                lo -= a1; hi += a0
            rects.append((lo, y0 - hw, hi, y0 + hw))
        elif x0 == x1:                                 # vertical segment
            lo, hi = (y0, y1) if y0 <= y1 else (y1, y0)
            if y0 <= y1:
                lo -= a0; hi += a1
            else:
                lo -= a1; hi += a0
            rects.append((x0 - hw, lo, x0 + hw, hi))
        else:                                          # diagonal: bound it
            rects.append((min(x0, x1) - hw, min(y0, y1) - hw,
                          max(x0, x1) + hw, max(y0, y1) + hw))

    # fill the notch at every interior corner
    for i in range(1, n - 1):
        x, y = pts[i]
        rects.append((x - hw, y - hw, x + hw, y + hw))
    return rects


def bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def poly_to_rects(pts):
    """Cut a polygon into rectangles by horizontal slabs.

    A bounding box is WRONG here: an L-shaped li1 route inside a cell would
    become a solid block covering the whole cell and short every pin together.
    So: slice at every vertex y, and for each slab work out which x-intervals
    are actually inside the polygon.
    """
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)
    if n < 3:
        return []
    ys = sorted({y for _, y in pts})
    if len(ys) < 2:
        return []
    rects = []
    for i in range(len(ys) - 1):
        y0, y1 = ys[i], ys[i + 1]
        ym = (y0 + y1) / 2.0
        xs = []
        for j in range(n):
            xa, ya = pts[j]
            xb, yb = pts[(j + 1) % n]
            if ya == yb:
                continue                       # horizontal edge, never crossed
            if min(ya, yb) < ym < max(ya, yb):
                xs.append(xa + (xb - xa) * (ym - ya) / (yb - ya))
        xs.sort()
        for k in range(0, len(xs) - 1, 2):     # even-odd fill rule
            x0, x1 = int(round(xs[k])), int(round(xs[k + 1]))
            if x1 > x0:
                rects.append((x0, y0, x1, y1))
    return rects


def parse(path):
    cells, cur = {}, None
    units = (1e-3, 1e-9)
    elem = layer = dtype = sname = string = None
    pts, width, pathtype, bgn, end = [], 0, 0, 0, 0
    strans, angle, colrow = 0, 0.0, None
    n_aref = 0

    for rt, dt, data in records(path):
        r = REC.get(rt)
        if r == 'UNITS' and len(data) >= 16:
            units = (gds_real(data[:8]), gds_real(data[8:16]))
        elif r == 'STRNAME':
            cur = data.rstrip(b'\x00').decode('ascii', 'replace')
            cells[cur] = {'rects': [], 'srefs': [], 'labels': []}
        elif r in ('BOUNDARY', 'PATH', 'SREF', 'AREF', 'TEXT', 'BOX'):
            elem = r
            layer = dtype = sname = string = None
            pts, width, pathtype, bgn, end = [], 0, 0, 0, 0
            strans, angle, colrow = 0, 0.0, None
        elif r == 'LAYER':
            layer = struct.unpack('>h', data[:2])[0]
        elif r in ('DATATYPE', 'TEXTTYPE', 'BOXTYPE'):
            dtype = struct.unpack('>h', data[:2])[0]
        elif r == 'WIDTH':
            width = struct.unpack('>i', data[:4])[0]
        elif r == 'PATHTYPE':
            pathtype = struct.unpack('>h', data[:2])[0]
        elif r == 'BGNEXTN':
            bgn = struct.unpack('>i', data[:4])[0]
        elif r == 'ENDEXTN':
            end = struct.unpack('>i', data[:4])[0]
        elif r == 'SNAME':
            sname = data.rstrip(b'\x00').decode('ascii', 'replace')
        elif r == 'STRANS':
            strans = struct.unpack('>H', data[:2])[0]
        elif r == 'ANGLE':
            angle = gds_real(data[:8])
        elif r == 'COLROW':
            colrow = struct.unpack('>hh', data[:4])
        elif r == 'STRING':
            string = data.rstrip(b'\x00').decode('ascii', 'replace')
        elif r == 'XY':
            pts = [struct.unpack('>ii', data[i:i + 8])
                   for i in range(0, len(data) - 7, 8)]
        elif r == 'ENDEL' and cur:
            c = cells[cur]
            key = (layer, dtype)
            if elem in ('BOUNDARY', 'BOX') and key in KEEP and pts:
                for r4 in poly_to_rects(pts):
                    c['rects'].append((layer, dtype) + r4)
            elif elem == 'PATH' and key in KEEP and pts:
                for r4 in path_to_rects(pts, width, pathtype, bgn, end):
                    c['rects'].append((layer, dtype) + r4)
            elif elem == 'SREF' and sname and pts:
                c['srefs'].append((sname, pts[0][0], pts[0][1],
                                   int(angle) % 360, bool(strans & 0x8000)))
            elif elem == 'AREF':
                n_aref += 1
            elif elem == 'TEXT' and string is not None and pts and key in LABELS:
                c['labels'].append((layer, dtype, string, pts[0][0], pts[0][1]))
            elem = None
    if n_aref:
        print(f'  WARNING: {n_aref} AREF records skipped (arrays unsupported)')
    return cells, units


# ---------------------------------------------------------------- PHASE 2

def xf_rect(r, ox, oy, ang, mir):
    """Move a rectangle into the parent frame: mirror, then rotate, then shift.

    Only 0/90/180/270 rotations keep a rectangle axis-aligned, so transforming
    two opposite corners and re-normalising is exact.
    """
    x1, y1, x2, y2 = r
    out = []
    for x, y in ((x1, y1), (x2, y2)):
        if mir:
            y = -y
        if ang == 90:
            x, y = -y, x
        elif ang == 180:
            x, y = -x, -y
        elif ang == 270:
            x, y = y, -x
        out.append((x + ox, y + oy))
    (ax, ay), (bx, by) = out
    return (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))


def build_cellpins(cells):
    """For each cell definition, pair its /16 pin shapes with the /5 label
    sitting inside them, so we learn each pin's name and footprint."""
    cellpins = {}
    for name, c in cells.items():
        pins = []
        labels = [(ly, s, x, y) for ly, dt, s, x, y in c['labels']]
        for layer, dt, x1, y1, x2, y2 in c['rects']:
            if (layer, dt) not in PINS:
                continue
            hit = None
            for ly, s, lx, ly_ in labels:
                if ly == layer and x1 <= lx <= x2 and y1 <= ly_ <= y2:
                    hit = s
                    break
            if hit:
                pins.append((hit, layer, dt, x1, y1, x2, y2))
        if pins:
            cellpins[name] = pins
    return cellpins


def flatten(cells, top):
    """Return absolute shapes and the instance list."""
    shapes, insts = [], []
    stack = [(top, 0, 0, 0, False, -1)]
    while stack:
        name, ox, oy, ang, mir, owner = stack.pop()
        c = cells.get(name)
        if c is None:
            continue
        for layer, dt, x1, y1, x2, y2 in c['rects']:
            r = xf_rect((x1, y1, x2, y2), ox, oy, ang, mir)
            shapes.append((layer, dt) + r + (owner,))
        for sname, x, y, sang, smir in c['srefs']:
            # compose the child transform with this one
            cx, cy = xf_rect((x, y, x, y), ox, oy, ang, mir)[:2]
            nang = (ang - sang if mir else ang + sang) % 360
            nmir = mir ^ smir
            child = cells.get(sname)
            if child is None:
                continue
            if child['srefs']:                       # a module: keep descending
                stack.append((sname, cx, cy, nang, nmir, owner))
            else:                                    # a leaf cell instance
                idx = len(insts)
                insts.append((idx, sname, cx, cy, nang, nmir))
                stack.append((sname, cx, cy, nang, nmir, idx))
    return shapes, insts


# ---------------------------------------------------------------- report

def main(path, out):
    print(f'reading {path} ...')
    cells, units = parse(path)
    dbu_nm = units[1] * 1e9

    referenced = {s for c in cells.values() for s, *_ in c['srefs']}
    tops = [n for n in cells if n not in referenced and cells[n]['srefs']]
    top = max(tops, key=lambda n: len(cells[n]['srefs']))
    print(f'  top cell = {top}   1 DBU = {dbu_nm:g} nm')

    cellpins = build_cellpins(cells)
    print(f'  cell definitions with named pins: {len(cellpins)}')

    shapes, insts = flatten(cells, top)
    print(f'  flattened: {len(shapes):,} rectangles, {len(insts):,} instances')

    per = Counter((l, d) for l, d, *_ in shapes)
    print('\n  shapes by layer:')
    for (l, d), n in sorted(per.items()):
        kind = ('routing' if (l, d) in ROUTING else
                'cut' if (l, d) in CUTS else 'pin')
        print(f'    {l:>3}/{d:<3} {n:>9,}   {kind}')

    xs1 = min(s[2] for s in shapes); ys1 = min(s[3] for s in shapes)
    xs2 = max(s[4] for s in shapes); ys2 = max(s[5] for s in shapes)
    print(f'\n  overall bbox: ({xs1*dbu_nm/1000:.2f}, {ys1*dbu_nm/1000:.2f}) '
          f'to ({xs2*dbu_nm/1000:.2f}, {ys2*dbu_nm/1000:.2f}) um')

    widths = Counter()
    for l, d, x1, y1, x2, y2, o in shapes:
        if (l, d) in ROUTING:
            widths[min(x2 - x1, y2 - y1)] += 1
    print('  most common routing wire thickness (nm): '
          f'{[w for w, _ in widths.most_common(6)]}')

    ports = [(s, ly, dt, x, y) for ly, dt, s, x, y in cells[top]['labels']]
    print(f'  top-level labels: {len(ports)}')

    data = {'shapes': shapes, 'insts': insts, 'cellpins': cellpins,
            'ports': ports, 'dbu_nm': dbu_nm, 'top': top,
            'ROUTING': ROUTING, 'CUTS': CUTS, 'PINS': PINS,
            'CUT_BRIDGE': CUT_BRIDGE}
    with open(out, 'wb') as f:
        pickle.dump(data, f)
    print(f'\n  wrote {out}')


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    if not a:
        print(__doc__)
        sys.exit(1)
    out = 'flat.pkl'
    if '--out' in sys.argv:
        out = sys.argv[sys.argv.index('--out') + 1]
        a = [z for z in a if z != out]
    else:
        out = a[0].rsplit('.', 1)[0] + '_flat.pkl'
    main(a[0], out)
