#!/usr/bin/env python3
"""
gds_netlist.py - Phase 3 + 4 of the extraction pipeline.

Phase 3: merge rectangles into nets.
         - shapes on the same layer that overlap or touch are one net
         - shapes on different layers join only through a cut (via)
Phase 4: attach cell pins to nets, and write a Verilog netlist.

Usage:
    python3 gds_netlist.py puzzle_flat.pkl
    python3 gds_netlist.py puzzle_flat.pkl --bucket 2000 --out puzzle.v
"""

import pickle
import sys
import time
from collections import Counter, defaultdict

# pins whose name means "this cell drives the net"
OUTPUT_PINS = {'X', 'Y', 'Q', 'Q_N', 'COUT', 'SUM', 'HI', 'LO', 'COUT_N'}
POWER_PINS = {'VPWR', 'VGND', 'VPB', 'VNB'}

# a pin shape on layer (L,16) is physically metal on layer (L,20)
PIN_TO_ROUTING = {(67, 16): (67, 20), (68, 16): (68, 20), (69, 16): (69, 20),
                  (70, 16): (70, 20), (71, 16): (71, 20), (72, 16): (72, 20)}

# a text label on layer (L,5) names the metal on layer (L,20)
LABEL_TO_ROUTING = {(67, 5): (67, 20), (68, 5): (68, 20), (69, 5): (69, 20),
                    (70, 5): (70, 20), (71, 5): (71, 20), (72, 5): (72, 20)}

CUT_BRIDGE = {
    (67, 44): ((67, 20), (68, 20)),   # mcon : li1  -> met1
    (68, 44): ((68, 20), (69, 20)),   # via  : met1 -> met2
    (69, 44): ((69, 20), (70, 20)),   # via2 : met2 -> met3
    (70, 44): ((70, 20), (71, 20)),   # via3 : met3 -> met4
    (71, 44): ((71, 20), (72, 20)),   # via4 : met4 -> met5
}


# ------------------------------------------------------------- union-find

class UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        p = self.p
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def overlaps(a, b):
    """True if two rectangles overlap OR touch along an edge."""
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def xf_rect(r, ox, oy, ang, mir):
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


class Index:
    """Spatial hash: only compare rectangles that share a grid bucket."""

    def __init__(self, bucket):
        self.b = bucket
        self.g = defaultdict(list)

    def add(self, i, r):
        b = self.b
        for bx in range(r[0] // b, r[2] // b + 1):
            for by in range(r[1] // b, r[3] // b + 1):
                self.g[(bx, by)].append(i)

    def query(self, r):
        b = self.b
        hits = set()
        for bx in range(r[0] // b, r[2] // b + 1):
            for by in range(r[1] // b, r[3] // b + 1):
                hits.update(self.g.get((bx, by), ()))
        return hits


# ------------------------------------------------------------------ main

def main(pkl, bucket, out_v):
    t0 = time.time()
    data = pickle.load(open(pkl, 'rb'))
    shapes, insts = data['shapes'], data['insts']
    cellpins, ports = data['cellpins'], data['ports']
    nm = data['dbu_nm']
    print(f'loaded {len(shapes):,} shapes, {len(insts):,} instances')

    # ---- group shapes by the routing layer they live on -------------------
    by_layer = defaultdict(list)          # (l,d) -> [(index, rect)]
    cuts = defaultdict(list)
    skipped = set()
    for i, (l, d, x1, y1, x2, y2, owner) in enumerate(shapes):
        key = (l, d)
        if key in CUT_BRIDGE:
            cuts[key].append((i, (x1, y1, x2, y2)))
        elif key == (66, 44):
            skipped.add(i)                 # licon: bridges to poly, not modelled
            continue
        else:
            key = PIN_TO_ROUTING.get(key, key)
            by_layer[key].append((i, (x1, y1, x2, y2)))

    uf = UF(len(shapes))

    # ---- Phase 3a: merge within each layer --------------------------------
    print('\nPhase 3a: merging shapes within each layer')
    index = {}
    for key in sorted(by_layer):
        items = by_layer[key]
        idx = Index(bucket)
        for i, r in items:
            idx.add(i, r)
        index[key] = idx
        rect = {i: r for i, r in items}
        pairs = 0
        for members in idx.g.values():
            n = len(members)
            for a in range(n):
                ia = members[a]
                ra = rect[ia]
                for b in range(a + 1, n):
                    ib = members[b]
                    pairs += 1
                    if uf.find(ia) != uf.find(ib) and overlaps(ra, rect[ib]):
                        uf.union(ia, ib)
        print(f'  {key[0]:>3}/{key[1]:<3} {len(items):>8,} shapes, '
              f'{pairs:>10,} comparisons   [{time.time()-t0:.1f}s]')

    # ---- Phase 3b: merge through the cuts ---------------------------------
    print('\nPhase 3b: joining layers through vias')
    for key in sorted(cuts):
        lower, upper = CUT_BRIDGE[key]
        li, ui = index.get(lower), index.get(upper)
        joined = orphan = 0
        for i, r in cuts[key]:
            below = [j for j in (li.query(r) if li else ())
                     if overlaps(r, shapes_rect(shapes, j))]
            above = [j for j in (ui.query(r) if ui else ())
                     if overlaps(r, shapes_rect(shapes, j))]
            if below and above:
                for j in below + above:
                    uf.union(i, j)
                joined += 1
            else:
                orphan += 1
        print(f'  {key[0]:>3}/{key[1]:<3} {len(cuts[key]):>8,} cuts   '
              f'joined {joined:>7,}   orphaned {orphan:>6,}   '
              f'[{time.time()-t0:.1f}s]')

    # ---- collect nets ------------------------------------------------------
    nets = defaultdict(list)
    for i in range(len(shapes)):
        if i not in skipped:
            nets[uf.find(i)].append(i)
    print(f'\n{len(nets):,} nets found')
    sizes = Counter(len(v) for v in nets.values())
    print('  net size histogram (shapes per net, top 8): '
          f'{sorted(sizes.items())[:8]}')
    biggest = sorted(nets.values(), key=len, reverse=True)[:3]
    print(f'  three largest nets hold {[len(b) for b in biggest]} shapes')

    # ---- Phase 4: attach pins ---------------------------------------------
    print('\nPhase 4: attaching cell pins to nets')
    pin_net = {}                     # (inst, pinname) -> net root
    unconnected = 0
    for idx, cname, ox, oy, ang, mir in insts:
        for pname, l, d, px1, py1, px2, py2 in cellpins.get(cname, ()):
            r = xf_rect((px1, py1, px2, py2), ox, oy, ang, mir)
            key = PIN_TO_ROUTING.get((l, d), (l, d))
            ind = index.get(key)
            found = None
            if ind:
                for j in ind.query(r):
                    if overlaps(r, shapes_rect(shapes, j)):
                        found = uf.find(j)
                        break
            if found is None:
                unconnected += 1
            else:
                pin_net[(idx, pname)] = found
    print(f'  {len(pin_net):,} pin connections, {unconnected:,} pins '
          f'with no metal found')

    # ---- name the nets -----------------------------------------------------
    name_of = {}
    for pname, l, d, x, y in ((p[0], p[1], p[2], p[3], p[4]) for p in ports):
        key = LABEL_TO_ROUTING.get((l, d), PIN_TO_ROUTING.get((l, d), (l, d)))
        ind = index.get(key)
        if not ind:
            continue
        probe = (x - 20, y - 20, x + 20, y + 20)
        for j in ind.query(probe):
            if overlaps(probe, shapes_rect(shapes, j)):
                name_of[uf.find(j)] = pname
                break
    print(f'  named {len(name_of)} nets from top-level port labels: '
          f'{sorted(set(name_of.values()))}')

    power = Counter()
    for (idx, pname), root in pin_net.items():
        if pname in ('VPWR', 'VGND'):
            power[(pname, root)] += 1
    for (pname, root), n in power.most_common(4):
        if root not in name_of:
            name_of[root] = pname
        print(f'  {pname:<5} net has {n:,} pin connections')

    counter = [0]

    def netname(root):
        if root not in name_of:
            counter[0] += 1
            name_of[root] = f'n{counter[0]}'
        return name_of[root]

    # ---- driver / load sanity check ---------------------------------------
    drivers = defaultdict(list)
    loads = defaultdict(list)
    for (idx, pname), root in pin_net.items():
        if pname in POWER_PINS:
            continue
        (drivers if pname in OUTPUT_PINS else loads)[root].append((idx, pname))
    multi = [r for r, v in drivers.items() if len(v) > 1]
    nodrv = [r for r in loads if r not in drivers and r not in name_of]
    print(f'\n  nets with >1 driver : {len(multi)}   (should be 0)')
    print(f'  nets with no driver : {len(nodrv)}   '
          f'(should be 0; ports are excluded)')

    # ---- emit Verilog ------------------------------------------------------
    portnames = sorted({p[0] for p in ports} - {'VPWR', 'VGND'})
    lines = ['// extracted from GDS geometry', f'module {data["top"]} (',
             '    ' + ',\n    '.join(portnames), ');', '']
    used = set()
    body = []
    for idx, cname, ox, oy, ang, mir in insts:
        pins = cellpins.get(cname)
        if not pins:
            continue
        conns = []
        seen_pins = set()
        for pname, *_ in pins:
            if pname in ('VPB', 'VNB') or pname in seen_pins:
                continue
            seen_pins.add(pname)
            root = pin_net.get((idx, pname))
            n = netname(root) if root is not None else "1'bz"
            used.add(n)
            conns.append(f'.{pname}({n})')
        body.append(f'  {cname} U{idx} ( ' + ', '.join(conns) + ' );')
    wires = sorted(used - set(portnames) - {"1'bz"})
    for w in wires:
        lines.append(f'  wire {w};')
    lines.append('')
    lines += body
    lines.append('endmodule')
    open(out_v, 'w').write('\n'.join(lines) + '\n')
    print(f'\nwrote {out_v}: {len(body):,} instances, {len(wires):,} wires '
          f'[{time.time()-t0:.1f}s total]')

    pickle.dump({'pin_net': pin_net, 'name_of': name_of, 'insts': insts,
                 'cellpins': cellpins, 'ports': ports},
                open(pkl.replace('_flat', '_nets'), 'wb'))
    print(f'wrote {pkl.replace("_flat", "_nets")}')


def shapes_rect(shapes, j):
    s = shapes[j]
    return (s[2], s[3], s[4], s[5])


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    if not a:
        print(__doc__)
        sys.exit(1)
    bucket = 2000
    out = a[0].replace('_flat.pkl', '.v')
    if '--bucket' in sys.argv:
        bucket = int(sys.argv[sys.argv.index('--bucket') + 1])
    if '--out' in sys.argv:
        out = sys.argv[sys.argv.index('--out') + 1]
    main(a[0], bucket, out)
