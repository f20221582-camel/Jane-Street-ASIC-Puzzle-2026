#!/usr/bin/env python3
"""
gds_cellinfo.py - show what is actually inside each cell DEFINITION.

Use it to identify mystery cells: a cell holding only metal + a cut layer is a
via stamp; a cell holding poly and diffusion is a real logic cell; a cell holding
other cells is a module.

Usage:
    python3 gds_cellinfo.py puzzle.gds
    python3 gds_cellinfo.py puzzle.gds INTERNAL_3 INTERNAL_7   # only these
    python3 gds_cellinfo.py puzzle.gds --all                   # include sky130 cells
"""

import struct
import sys
from collections import Counter

REC = {0x03: 'UNITS', 0x06: 'STRNAME', 0x08: 'BOUNDARY', 0x09: 'PATH',
       0x0A: 'SREF', 0x0B: 'AREF', 0x0C: 'TEXT', 0x0D: 'LAYER',
       0x0E: 'DATATYPE', 0x10: 'XY', 0x11: 'ENDEL', 0x12: 'SNAME',
       0x16: 'TEXTTYPE', 0x19: 'STRING'}

# sky130 layer/datatype meanings
LAYERS = {
    (64, 20): 'nwell', (64, 16): 'nwell.pin', (64, 59): 'nwell.label',
    (65, 20): 'diff', (65, 44): 'tap',
    (66, 20): 'poly', (66, 44): 'licon1 (contact)', (66, 15): 'poly.marker',
    (67, 20): 'li1', (67, 44): 'mcon (li1->met1)', (67, 16): 'li1.pin', (67, 5): 'li1.label',
    (68, 20): 'met1', (68, 44): 'via (met1->met2)', (68, 16): 'met1.pin', (68, 5): 'met1.label',
    (69, 20): 'met2', (69, 44): 'via2 (met2->met3)', (69, 16): 'met2.pin', (69, 5): 'met2.label',
    (70, 20): 'met3', (70, 44): 'via3 (met3->met4)', (70, 16): 'met3.pin', (70, 5): 'met3.label',
    (71, 20): 'met4', (71, 44): 'via4', (71, 16): 'met4.pin', (71, 5): 'met4.label',
    (72, 20): 'met5', (72, 16): 'met5.pin', (72, 5): 'met5.label',
    (78, 44): 'hvtp', (81, 4): 'areaid.standardc', (81, 23): 'areaid',
    (83, 44): 'text (cell name)', (93, 44): 'nsdm (n+ implant)',
    (94, 20): 'psdm (p+ implant)', (95, 20): 'npc',
    (122, 16): 'nwell.pin2', (235, 4): 'prBoundary', (236, 0): 'obstruction',
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


def parse(path):
    cells, cur, units = {}, None, (1e-3, 1e-9)
    elem = layer = dtype = sname = string = None
    pts = []
    for rt, dt, data in records(path):
        r = REC.get(rt)
        if r == 'UNITS' and len(data) >= 16:
            units = (gds_real(data[:8]), gds_real(data[8:16]))
        elif r == 'STRNAME':
            cur = data.rstrip(b'\x00').decode('ascii', 'replace')
            cells[cur] = {'shapes': Counter(), 'srefs': Counter(),
                          'texts': [], 'bbox': None}
        elif r in ('BOUNDARY', 'PATH', 'SREF', 'AREF', 'TEXT'):
            elem, layer, dtype, sname, string, pts = r, None, None, None, None, []
        elif r == 'LAYER':
            layer = struct.unpack('>h', data[:2])[0]
        elif r in ('DATATYPE', 'TEXTTYPE'):
            dtype = struct.unpack('>h', data[:2])[0]
        elif r == 'SNAME':
            sname = data.rstrip(b'\x00').decode('ascii', 'replace')
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
            elif elem in ('SREF', 'AREF') and sname:
                c['srefs'][sname] += 1
            elif elem == 'TEXT' and string is not None:
                c['texts'].append((layer, dtype, string))
            elem = None
    return cells, units


def classify(c):
    L = set(c['shapes'])
    if c['srefs'] and any(not n.startswith('VIA') for n in c['srefs']):
        return 'MODULE (contains cell instances)'
    if (66, 20) in L or (65, 20) in L:
        return 'LOGIC CELL (has poly/diffusion = transistors)'
    routing = {(67, 20), (68, 20), (69, 20), (70, 20), (71, 20), (72, 20)}
    cuts = {(67, 44), (68, 44), (69, 44), (70, 44), (71, 44), (66, 44)}
    if L & cuts and L & routing:
        return 'VIA / ROUTING STAMP (metal + a cut layer, no transistors)'
    if L <= routing:
        return 'METAL-ONLY stamp'
    return 'unclassified'


def main(path, wanted=None, show_all=False):
    cells, units = parse(path)
    nm = units[1] * 1e9
    names = wanted or [n for n in sorted(cells)
                       if show_all or not n.startswith('sky130_fd_sc_hd__')]
    print('=' * 72)
    for n in names:
        c = cells.get(n)
        if c is None:
            print(f'  {n}: NOT FOUND in this file')
            continue
        bb = c['bbox']
        size = (f'{(bb[2]-bb[0])*nm/1000:.3f} x {(bb[3]-bb[1])*nm/1000:.3f} um'
                if bb else 'no geometry')
        print(f'\n{n}')
        print(f'  size      : {size}')
        print(f'  verdict   : {classify(c)}')
        print(f'  instances : {sum(c["srefs"].values())}'
              + (f'  {dict(c["srefs"].most_common(6))}' if c['srefs'] else ''))
        print(f'  shapes    : {sum(c["shapes"].values())}')
        for (ly, dt), k in sorted(c['shapes'].items()):
            print(f'      {ly:>4}/{dt:<3} {k:>7,}   {LAYERS.get((ly, dt), "?")}')
        if c['texts']:
            vals = sorted({t[2] for t in c['texts']})
            print(f'  labels    : {len(c["texts"])}  {vals[:20]}'
                  + (' ...' if len(vals) > 20 else ''))
    print('\n' + '=' * 72)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__)
        sys.exit(1)
    main(args[0], args[1:] or None, '--all' in sys.argv)
