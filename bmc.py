#!/usr/bin/env python3
"""
bmc.py - Phase 6d done properly: bounded model checking with a SAT solver.

Unrolls the circuit over K clock cycles, asserts `success` at some cycle,
and solves for the input bits. Unlike random search this is COMPLETE:
if it says UNSAT for K cycles, no input of that length can work.

  pip install python-sat --break-system-packages
  python3 bmc.py warmup_nets.pkl --K 12 --succ S    --inputs A B --hold en
  python3 bmc.py puzzle_nets.pkl --K 40 --succ success --inputs I --hold enable
"""
import sys, time, itertools
sys.path.insert(0, '.')
from sim import Circuit
from gatelib import G
from collections import deque
from pysat.solvers import Cadical153
from pysat.formula import IDPool

OUT = {'X', 'Y', 'Q', 'HI', 'LO'}


def build(path, K, succname, inputs, hold):
    c = Circuit(path)
    qnet = {f: c.pins[f].get('Q') for f in c.flops}
    dnet = {f: c.pins[f].get('D') for f in c.flops}
    q2f = {n: f for f, n in qnet.items() if n}
    succ_net = c.port[succname]
    succ_flop = q2f.get(succ_net)

    # which flops matter: transitive closure of "D depends on Q of"
    def fanin_flops(start):
        seen, ff, q = set(), set(), deque([start])
        while q:
            n = q.popleft()
            if n in seen: continue
            seen.add(n)
            if n in q2f: ff.add(q2f[n]); continue
            gi = c.drv.get(n)
            if gi is None: continue
            for p, nn in c.pins[gi].items():
                if p not in OUT: q.append(nn)
        return ff, seen

    need = {succ_flop} if succ_flop else set()
    if not need:                       # success is combinational
        ff, _ = fanin_flops(succ_net); need = set(ff)
    changed = True
    while changed:
        changed = False
        for f in list(need):
            if dnet[f] is None: continue
            ff, _ = fanin_flops(dnet[f])
            for g in ff:
                if g not in need:
                    need.add(g); changed = True
    print(f'  {len(need)} of {len(c.flops)} flops matter for {succname}')

    gates = set()
    for f in need:
        if dnet[f] is None: continue
        _, nets = fanin_flops(dnet[f])
        for n in nets:
            gi = c.drv.get(n)
            if gi is not None and c.base[gi] in G:
                gates.add(gi)
    if succ_flop is None:
        _, nets = fanin_flops(succ_net)
        for n in nets:
            gi = c.drv.get(n)
            if gi is not None and c.base[gi] in G: gates.add(gi)
    gates = sorted(gates)
    print(f'  encoding {len(gates)} gates over {K} cycles')

    pool = IDPool(); cls = []
    def V(net, t): return pool.id(('n', net, t))

    def fix(net, t, val):
        cls.append([V(net, t) if val else -V(net, t)])

    # gate CNF by truth-table enumeration (fan-in is small)
    for t in range(K):
        for gi in gates:
            b = c.base[gi]
            opin, fn = G[b]
            on = c.pins[gi].get(opin)
            if on is None: continue
            ins = [(p, n) for p, n in c.pins[gi].items() if p not in OUT]
            names = [p for p, _ in ins]
            for combo in itertools.product((0, 1), repeat=len(ins)):
                d = dict(zip(names, combo))
                try: val = fn(d)
                except KeyError: val = 0
                cl = []
                for (p, n), bit in zip(ins, combo):
                    cl.append(-V(n, t) if bit else V(n, t))
                cl.append(V(on, t) if val else -V(on, t))
                cls.append(cl)
        # ports
        for nm, n in c.port.items():
            if nm in inputs: continue
            if nm in hold: fix(n, t, 1)
            elif nm == 'rst_n': fix(n, t, 1)
        # tie cells
        for n, val in c.consts.items(): fix(n, t, val)

    # initial state (after reset)
    for f in need:
        n = qnet[f]
        if n is None: continue
        if c.base[f] == 'dfstp': fix(n, 0, 1)
        elif c.base[f] == 'dfrtp': fix(n, 0, 0)
        # dfxtp has no reset pin -> unknown at power-up, leave free
    # flop update
    for t in range(K - 1):
        for f in need:
            qn, dn = qnet[f], dnet[f]
            if qn is None or dn is None: continue
            a, b_ = V(dn, t), V(qn, t + 1)
            cls += [[-a, b_], [a, -b_]]
    # goal: success at some cycle
    goal = [V(succ_net, t) for t in range(1, K)]
    cls.append(goal)
    return c, pool, cls, V, succ_net


def main():
    path = [a for a in sys.argv[1:] if not a.startswith('--')][0]
    K = int(sys.argv[sys.argv.index('--K') + 1]) if '--K' in sys.argv else 24
    succ = sys.argv[sys.argv.index('--succ') + 1] if '--succ' in sys.argv else 'success'
    inputs = []
    if '--inputs' in sys.argv:
        i = sys.argv.index('--inputs') + 1
        while i < len(sys.argv) and not sys.argv[i].startswith('--'):
            inputs.append(sys.argv[i]); i += 1
    hold = []
    if '--hold' in sys.argv:
        i = sys.argv.index('--hold') + 1
        while i < len(sys.argv) and not sys.argv[i].startswith('--'):
            hold.append(sys.argv[i]); i += 1

    t0 = time.time()
    c, pool, cls, V, succ_net = build(path, K, succ, set(inputs), set(hold))
    print(f'  {len(cls):,} clauses, {pool.top:,} vars  [{time.time()-t0:.1f}s]')
    s = Cadical153(bootstrap_with=cls)
    print('  solving...')
    ok = s.solve()
    print(f'  {"SAT" if ok else "UNSAT"}  [{time.time()-t0:.1f}s]')
    if not ok:
        print(f'  => no input of {K} cycles can assert {succ}. Try a larger --K.')
        return
    model = set(l for l in s.get_model() if l > 0)
    for nm in inputs:
        n = c.port[nm]
        bits = ''.join('1' if V(n, t) in model else '0' for t in range(K))
        print(f'  {nm} = {bits}')
    for t in range(K):
        if V(succ_net, t) in model:
            print(f'  success first true at cycle {t}'); break
    # verify with the independent simulator and print the output bytes
    seqs = {nm: [1 if V(c.port[nm], t) in model else 0 for t in range(K)]
            for nm in inputs}
    for nm in hold: seqs[nm] = [1]*K
    st = c.reset(); st, _ = c.step(st, {'rst_n':0})
    fired=False; out=[]
    for t in range(K):
        inp = {nm: seqs[nm][t] for nm in seqs}; inp['rst_n']=1
        st, v = c.step(st, inp)
        if c.net(v, succ): fired=True
        if fired:
            out.append(sum((c.net(v, f'O[{k}]') or 0) << k for k in range(8)))
    print(f"  SIMULATOR CHECK: {succ} fired = {fired}")
    if out:
        print('  O bytes LSB-first:', out[:40])
        txt=''.join(chr(b) if 32<=b<127 else '.' for b in out)
        print('  as text:', txt[:80])
        rev=[int(f'{b:08b}'[::-1],2) for b in out]
        print('  as text (MSB-first):',
              ''.join(chr(b) if 32<=b<127 else '.' for b in rev)[:80])


if __name__ == '__main__':
    main()
