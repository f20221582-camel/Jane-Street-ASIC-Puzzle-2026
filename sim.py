#!/usr/bin/env python3
"""
sim.py - Phase 6: gate-level simulator for the extracted netlist.

Usage:
    python3 sim.py warmup_nets.pkl --selftest       # validate on the warm-up
    python3 sim.py puzzle_nets.pkl --probe          # explore the puzzle
"""
import pickle, sys
from collections import defaultdict, Counter, deque
from gatelib import G, SEQ, PHYS

OUT_PINS = {'X', 'Y', 'Q', 'HI', 'LO'}
PWR = {'VPWR', 'VGND', 'VPB', 'VNB', 'DIODE'}


class Circuit:
    def __init__(self, pklpath):
        d = pickle.load(open(pklpath, 'rb'))
        self.name_of = d['name_of']
        insts = d['insts']
        pin_net = d['pin_net']
        self.cell = {i: c.split('__')[1] for i, c, *_ in insts if '__' in c}
        self.pos = {i: (x, y) for i, c, x, y, a, m in insts if '__' in c}
        self.base = {i: c.rsplit('_', 1)[0] for i, c in self.cell.items()}

        self.pins = defaultdict(dict)
        for (i, p), n in pin_net.items():
            if p in PWR:
                continue
            self.pins[i][p] = n

        self.drv = {}                      # net -> instance driving it
        for i, pd in self.pins.items():
            for p, n in pd.items():
                if p in OUT_PINS:
                    self.drv[n] = i

        self.flops = [i for i in self.cell if self.base[i] in SEQ]
        self.consts = {}                   # net -> fixed value from tie cells
        for i in self.cell:
            if self.base[i] == 'conb':
                if 'HI' in self.pins[i]: self.consts[self.pins[i]['HI']] = 1
                if 'LO' in self.pins[i]: self.consts[self.pins[i]['LO']] = 0
        self.combs = [i for i in self.cell
                      if self.base[i] not in SEQ and self.base[i] not in PHYS
                      and self.base[i] in G]
        unknown = {self.base[i] for i in self.cell
                   if self.base[i] not in SEQ and self.base[i] not in PHYS
                   and self.base[i] not in G and self.base[i] != 'conb'}
        if unknown:
            print('  WARNING unknown cell types:', unknown)

        self.port = {v: k for k, v in self.name_of.items()
                     if not v.startswith('n')}
        self.looped = []
        self.order = self._toposort()
        if self.looped:
            print(f'  {len(self.looped)} gates resolved by fixpoint iteration')
        print(f'  {len(self.flops)} flops, {len(self.combs)} combinational gates, '
              f'{len(self.order)} in eval order')

    def _toposort(self):
        """Order combinational gates so inputs are ready before outputs."""
        ready = set(self.port.values()) | set(self.consts)
        for f in self.flops:
            q = self.pins[f].get('Q')
            if q is not None:
                ready.add(q)
        pending = list(self.combs)
        order, guard = [], 0
        while pending and guard < 200:
            guard += 1
            nxt = []
            for i in pending:
                ins = [n for p, n in self.pins[i].items() if p not in OUT_PINS]
                if all(n in ready for n in ins):
                    order.append(i)
                    for p, n in self.pins[i].items():
                        if p in OUT_PINS:
                            ready.add(n)
                else:
                    nxt.append(i)
            if len(nxt) == len(pending):
                self.looped = nxt
                break
            pending = nxt
        return order

    # ------------------------------------------------------------ evaluate
    def eval_comb(self, state, inputs):
        """state: {flop -> bit}. inputs: {portname -> bit}. Returns net values."""
        v = dict(self.consts)
        for nm, n in self.port.items():
            v[n] = inputs.get(nm, 0)
        for f in self.flops:
            q = self.pins[f].get('Q')
            if q is not None:
                v[q] = state.get(f, 0)
        for i in list(self.order) + list(self.looped) * 4:
            b = self.base[i]
            opin, fn = G[b]
            p = {k: v.get(n, 0) for k, n in self.pins[i].items() if k not in OUT_PINS}
            try:
                r = fn(p)
            except KeyError:
                r = 0
            on = self.pins[i].get(opin)
            if on is not None:
                v[on] = r
        return v

    def step(self, state, inputs):
        """One clock edge. Returns (new_state, net_values)."""
        v = self.eval_comb(state, inputs)
        rst = inputs.get('rst_n', 1)
        new = {}
        for f in self.flops:
            b = self.base[f]
            if not rst:
                new[f] = 1 if b == 'dfstp' else 0
            else:
                dn = self.pins[f].get('D')
                new[f] = v.get(dn, 0) if dn is not None else 0
        return new, v

    def reset(self):
        st = {f: (1 if self.base[f] == 'dfstp' else 0) for f in self.flops}
        return st

    def net(self, v, name):
        n = self.port.get(name)
        return v.get(n, None) if n is not None else None


def selftest(path):
    """warm-up: shift A and B in serially, S should assert when A+B == 496."""
    c = Circuit(path)
    for A, B in ((248, 248), (255, 241), (200, 296 & 255), (100, 100), (0, 0)):
        st = c.reset()
        st, _ = c.step(st, {'rst_n': 0, 'en': 0})
        for k in range(8):                       # MSB first
            a = (A >> (7 - k)) & 1
            b = (B >> (7 - k)) & 1
            st, v = c.step(st, {'A': a, 'B': b, 'en': 1, 'rst_n': 1})
        st2, v = c.step(st, {'A': 0, 'B': 0, 'en': 0, 'rst_n': 1})
        s = c.net(v, 'S')
        print(f'  A={A:3d} B={B:3d}  A+B={A+B:4d}   S={s}'
              + ('   <-- SUCCESS' if s else ''))


def probe(path):
    c = Circuit(path)
    st = c.reset()
    st, v = c.step(st, {'rst_n': 0, 'enable': 0, 'I': 0})
    print('  after reset: success =', c.net(v, 'success'),
          ' O =', [c.net(v, f'O[{k}]') for k in range(8)])
    import random
    random.seed(1)
    for trial in range(3):
        st = c.reset()
        st, _ = c.step(st, {'rst_n': 0, 'enable': 0, 'I': 0})
        bits = [random.randint(0, 1) for _ in range(64)]
        hits = 0
        for b in bits:
            st, v = c.step(st, {'I': b, 'enable': 1, 'rst_n': 1})
            hits += c.net(v, 'success') or 0
        print(f'  random 64-bit input #{trial}: success asserted {hits} times')


if __name__ == '__main__':
    p = [a for a in sys.argv[1:] if not a.startswith('--')][0]
    if '--selftest' in sys.argv:
        selftest(p)
    else:
        probe(p)
