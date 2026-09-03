#!/usr/bin/env python3
"""
morse_decode.py - decode the off-die annotation row in a GDSII layout.

Reads the placements of two marker cell types, sorts them left to right,
measures the gaps between them, and decodes as Morse code.

Morse timing, in units where a dot = 1:
    dot                1        dash               3
    gap inside letter  1        gap between words  7
    gap between letters 3

Usage:
    python3 morse_decode.py puzzle.gds
    python3 morse_decode.py puzzle.gds --cells INTERNAL_3 INTERNAL_7
    python3 morse_decode.py puzzle.gds --unit 1380     # force the unit length
"""

import struct
import sys
from collections import Counter

REC = {0x03: 'UNITS', 0x06: 'STRNAME', 0x08: 'BOUNDARY', 0x09: 'PATH',
       0x0A: 'SREF', 0x0B: 'AREF', 0x0C: 'TEXT', 0x0D: 'LAYER',
       0x0E: 'DATATYPE', 0x10: 'XY', 0x11: 'ENDEL', 0x12: 'SNAME'}

MORSE = {
    '.-': 'A', '-...': 'B', '-.-.': 'C', '-..': 'D', '.': 'E', '..-.': 'F',
    '--.': 'G', '....': 'H', '..': 'I', '.---': 'J', '-.-': 'K', '.-..': 'L',
    '--': 'M', '-.': 'N', '---': 'O', '.--.': 'P', '--.-': 'Q', '.-.': 'R',
    '...': 'S', '-': 'T', '..-': 'U', '...-': 'V', '.--': 'W', '-..-': 'X',
    '-.--': 'Y', '--..': 'Z',
    '-----': '0', '.----': '1', '..---': '2', '...--': '3', '....-': '4',
    '.....': '5', '-....': '6', '--...': '7', '---..': '8', '----.': '9',
    '.-.-.-': '.', '--..--': ',', '..--..': '?', '-..-.': '/', '-....-': '-',
    '-.--.': '(', '-.--.-': ')', '.----.': "'", '---...': ':', '.-.-.': '+',
    '-...-': '=', '.--.-.': '@', '..--.-': '_', '...-..-': '$',
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
    """Return {cellname: {'w':width,'h':height,'srefs':[(name,x,y)]}} and nm/DBU."""
    cells, cur, units = {}, None, (1e-3, 1e-9)
    elem = layer = sname = None
    pts = []
    for rt, dt, data in records(path):
        r = REC.get(rt)
        if r == 'UNITS' and len(data) >= 16:
            units = (gds_real(data[:8]), gds_real(data[8:16]))
        elif r == 'STRNAME':
            cur = data.rstrip(b'\x00').decode('ascii', 'replace')
            cells[cur] = {'bbox': None, 'srefs': []}
        elif r in ('BOUNDARY', 'PATH', 'SREF', 'AREF', 'TEXT'):
            elem, layer, sname, pts = r, None, None, []
        elif r == 'LAYER':
            layer = struct.unpack('>h', data[:2])[0]
        elif r == 'SNAME':
            sname = data.rstrip(b'\x00').decode('ascii', 'replace')
        elif r == 'XY':
            pts = [struct.unpack('>ii', data[i:i + 8]) for i in range(0, len(data) - 7, 8)]
        elif r == 'ENDEL' and cur:
            c = cells[cur]
            if elem in ('BOUNDARY', 'PATH') and layer is not None:
                for x, y in pts:
                    b = c['bbox']
                    c['bbox'] = [x, y, x, y] if b is None else \
                        [min(b[0], x), min(b[1], y), max(b[2], x), max(b[3], y)]
            elif elem in ('SREF', 'AREF') and sname and pts:
                c['srefs'].append((sname, pts[0][0], pts[0][1]))
            elem = None
    return cells, units


def decode(symbols, gaps, unit, letter_gap=3, word_gap=7):
    """Turn symbols + gaps into text. Gaps are in database units."""
    letters, cur, text = [], '', ''
    for i, s in enumerate(symbols):
        cur += s
        g = gaps[i] if i < len(gaps) else None
        if g is None:
            letters.append(cur)
            break
        u = g / unit
        if u >= word_gap - 1:            # word break
            letters.append(cur)
            letters.append(' ')
            cur = ''
        elif u >= letter_gap - 1:        # letter break
            letters.append(cur)
            cur = ''
        # else: same letter, keep accumulating
    for L in letters:
        text += ' ' if L == ' ' else MORSE.get(L, f'[{L}]')
    return text, [L for L in letters if L != ' ']


def main(path, names, forced_unit=None):
    cells, units = parse(path)
    nm = units[1] * 1e9

    widths = {}
    for n in names:
        c = cells.get(n)
        if c is None or not c['bbox']:
            print(f'  {n}: not found or has no geometry')
            return
        widths[n] = c['bbox'][2] - c['bbox'][0]

    # every placement of the marker cells, anywhere in the file
    marks = []
    for parent, c in cells.items():
        for sname, x, y in c['srefs']:
            if sname in names:
                marks.append((x, y, sname, parent))
    if not marks:
        print('no placements of', names)
        return

    ys = Counter(y for x, y, s, p in marks)
    print('=' * 70)
    print(f'{len(marks)} marker placements, on {len(ys)} distinct row(s)')
    for y, k in ys.most_common():
        print(f'   y = {y:>10,} DBU = {y*nm/1000:>9.2f} um   ({k} cells)')
    for n in names:
        print(f'   {n}: width {widths[n]:,} DBU = {widths[n]*nm/1000:.3f} um')

    row = sorted([m for m in marks if m[1] == ys.most_common(1)[0][0]])
    unit = forced_unit or min(widths.values())
    print(f'\nunit length = {unit:,} DBU = {unit*nm/1000:.3f} um')
    dot_cell = min(widths, key=widths.get)

    symbols, gaps = [], []
    print(f'\n{"#":>3} {"x (um)":>10} {"cell":>12} {"sym":>4} {"gap um":>9} {"units":>7}')
    for i, (x, y, s, parent) in enumerate(row):
        sym = '.' if s == dot_cell else '-'
        symbols.append(sym)
        if i + 1 < len(row):
            gap = row[i + 1][0] - (x + widths[s])
            gaps.append(gap)
            print(f'{i:>3} {x*nm/1000:>10.2f} {s:>12} {sym:>4} '
                  f'{gap*nm/1000:>9.3f} {gap/unit:>7.2f}')
        else:
            print(f'{i:>3} {x*nm/1000:>10.2f} {s:>12} {sym:>4} {"-":>9} {"-":>7}')

    print(f'\nraw symbol string: {"".join(symbols)}')
    print(f'gap histogram (in units): '
          f'{sorted(Counter(round(g/unit) for g in gaps).items())}')

    text, letters = decode(symbols, gaps, unit)
    print(f'\ngrouped letters : {" ".join(letters)}')
    print(f'DECODED         : {text}')
    print('=' * 70)


if __name__ == '__main__':
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        sys.exit(1)
    path = argv[0]
    names = ['INTERNAL_3', 'INTERNAL_7']
    unit = None
    if '--cells' in argv:
        i = argv.index('--cells')
        names = [a for a in argv[i + 1:] if not a.startswith('--')]
    if '--unit' in argv:
        unit = int(argv[argv.index('--unit') + 1])
    main(path, names, unit)
