#!/usr/bin/env python3
"""
gds_def.py - Phase 5: write a DEF placement file from the extracted data.

Usage:
    python3 gds_def.py puzzle_flat.pkl puzzle_nets.pkl --out puzzle.def
"""
import pickle, sys
from collections import Counter, defaultdict

SITE_W, ROW_H = 460, 2720          # sky130_fd_sc_hd unithd site
# GDS (angle, mirror) -> DEF orientation
ORIENT = {(0, False): 'N', (90, False): 'W', (180, False): 'S', (270, False): 'E',
          (0, True): 'FS', (90, True): 'FW', (180, True): 'FN', (270, True): 'FE'}
OUT_PINS = {'X', 'Y', 'Q', 'HI', 'LO'}
SKIP_PINS = {'VPWR', 'VGND', 'VPB', 'VNB'}


def main(flatpkl, netpkl, out):
    fd = pickle.load(open(flatpkl, 'rb'))
    nd = pickle.load(open(netpkl, 'rb'))
    insts, cellpins = nd['insts'], nd['cellpins']
    pin_net, name_of, ports = nd['pin_net'], nd['name_of'], nd['ports']
    top = fd['top']

    cells = [(i, c, x, y, a, m) for i, c, x, y, a, m in insts
             if c.startswith('sky130_fd_sc_hd__')]
    print(f'{len(cells)} standard cells')

    xs = [x for _, _, x, y, _, _ in cells]
    ys = [y for _, _, _, y, _, _ in cells if y >= 0]
    die = (0, 0, max(200000, max(xs) + SITE_W), max(300000, max(ys) + ROW_H))

    # rows: a mirrored cell's origin sits at the TOP of its row
    rowset = Counter()
    for i, c, x, y, a, m in cells:
        if y < 0:
            continue
        rowset[(y - ROW_H) if m else y] += 1
    rows = sorted(rowset)
    print(f'{len(rows)} rows, pitch {rows[1]-rows[0] if len(rows)>1 else "?"} nm')

    # nets -> list of (instname, pin)
    netpins = defaultdict(list)
    for (idx, pname), root in pin_net.items():
        if pname in SKIP_PINS:
            continue
        netpins[root].append((f'U{idx}', pname))
    counter = [0]
    names = dict(name_of)

    def nname(root):
        if root not in names:
            counter[0] += 1
            names[root] = f'n{counter[0]}'
        return names[root]

    portnames = sorted({p[0] for p in ports} - {'VPWR', 'VGND'})
    L = []
    L.append('VERSION 5.8 ;')
    L.append('DIVIDERCHAR "/" ;')
    L.append('BUSBITCHARS "[]" ;')
    L.append(f'DESIGN {top} ;')
    L.append('UNITS DISTANCE MICRONS 1000 ;')
    L.append(f'DIEAREA ( {die[0]} {die[1]} ) ( {die[2]} {die[3]} ) ;')
    L.append('')
    for k, ry in enumerate(rows):
        o = 'N' if k % 2 == 0 else 'FS'
        n = (die[2] - die[0]) // SITE_W
        L.append(f'ROW ROW_{k} unithd {die[0]} {ry} {o} DO {n} BY 1 '
                 f'STEP {SITE_W} 0 ;')
    L.append('')
    L.append(f'COMPONENTS {len(cells)} ;')
    for i, c, x, y, a, m in cells:
        L.append(f'  - U{i} {c} + PLACED ( {x} {y} ) {ORIENT.get((a, m), "N")} ;')
    L.append('END COMPONENTS')
    L.append('')
    L.append(f'PINS {len(portnames)} ;')
    for p in ports:
        nm, ly, dt, px, py = p[0], p[1], p[2], p[3], p[4]
        if nm in ('VPWR', 'VGND'):
            continue
        direc = 'OUTPUT' if nm.startswith('O[') or nm == 'success' else 'INPUT'
        L.append(f'  - {nm} + NET {nm} + DIRECTION {direc} + USE SIGNAL')
        L.append(f'    + LAYER met{ly-67} ( -70 -70 ) ( 70 70 ) '
                 f'+ PLACED ( {px} {py} ) N ;')
    L.append('END PINS')
    L.append('')
    real = {r: v for r, v in netpins.items() if v}
    L.append(f'NETS {len(real)} ;')
    for root, pl in real.items():
        conn = ' '.join(f'( {i} {p} )' for i, p in pl)
        L.append(f'  - {nname(root)} {conn} + USE SIGNAL ;')
    L.append('END NETS')
    L.append('')
    L.append('SPECIALNETS 2 ;')
    L.append('  - VPWR ( * VPWR ) + USE POWER ;')
    L.append('  - VGND ( * VGND ) + USE GROUND ;')
    L.append('END SPECIALNETS')
    L.append('')
    L.append('END DESIGN')
    open(out, 'w').write('\n'.join(L) + '\n')
    print(f'wrote {out}: {len(cells)} components, {len(real)} nets, '
          f'{len(portnames)} pins, {len(rows)} rows')


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else 'out.def'
    main(a[0], a[1], out)
