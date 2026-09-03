#!/usr/bin/env python3
"""
solve.py - Phase 6d: search for the input sequence that asserts `success`.

  python3 solve.py puzzle_nets.pkl --sweep          # structured patterns first (fast)
  python3 solve.py puzzle_nets.pkl --climb --len 48 # guided hill-climb
  python3 solve.py puzzle_nets.pkl --random         # brute random
  python3 solve.py puzzle_nets.pkl --replay 1011... # re-run a found answer, print O[]

Stops and prints the answer string from O[7:0] as soon as success fires.
"""
import sys, random, time, itertools
from collections import deque
sys.path.insert(0, '.')
from sim import Circuit

OUT = {'X', 'Y', 'Q', 'HI', 'LO'}


class Solver:
    def __init__(self, path):
        self.c = c = Circuit(path)
        self.succ = c.port['success']
        sf = c.drv[self.succ]
        self.dnet = c.pins[sf]['D']
        qflop = {c.pins[f].get('Q'): f for f in c.flops}
        cone, seen, q = [], set(), deque([self.dnet])
        while q:
            n = q.popleft()
            if n in seen:
                continue
            seen.add(n)
            if n in qflop or n in c.consts or n in c.port.values():
                continue
            gi = c.drv.get(n)
            if gi is None:
                continue
            cone.append(n)
            for p, nn in c.pins[gi].items():
                if p not in OUT:
                    q.append(nn)
        self.cone = cone
        print(f'  success cone: {len(cone)} internal nodes')

    def run(self, bits, tail=60, capture=False):
        """Feed bits into I with enable=1. Return (best_score, cycle_hit or None)."""
        c = self.c
        st = c.reset()
        st, _ = c.step(st, {'rst_n': 0, 'enable': 0, 'I': 0})
        best = 0
        seq = list(bits) + [0] * tail
        for k, b in enumerate(seq):
            st, v = c.step(st, {'rst_n': 1, 'enable': 1, 'I': b})
            if c.net(v, 'success'):
                return 10 ** 9, k
            s = sum(v.get(n, 0) for n in self.cone)
            if s > best:
                best = s
        return best, None

    def emit(self, bits, cycles=64):
        """Replay and print the bytes appearing on O[7:0] after success."""
        c = self.c
        st = c.reset()
        st, _ = c.step(st, {'rst_n': 0, 'enable': 0, 'I': 0})
        out, fired = [], False
        for b in list(bits) + [0] * cycles:
            st, v = c.step(st, {'rst_n': 1, 'enable': 1, 'I': b})
            if c.net(v, 'success'):
                fired = True
            if fired:
                byte = sum((c.net(v, f'O[{k}]') or 0) << k for k in range(8))
                out.append(byte)
        print('  success fired:', fired)
        print('  O bytes:', out[:64])
        print('  as text :', ''.join(chr(b) if 32 <= b < 127 else '.' for b in out))
        byte_msb = None
        return out


def main():
    path = [a for a in sys.argv[1:] if not a.startswith('--')][0]
    s = Solver(path)
    seed = int(sys.argv[sys.argv.index('--seed') + 1]) if '--seed' in sys.argv else 1
    random.seed(seed)
    L = int(sys.argv[sys.argv.index('--len') + 1]) if '--len' in sys.argv else 48

    if '--replay' in sys.argv:
        bits = [int(ch) for ch in sys.argv[sys.argv.index('--replay') + 1] if ch in '01']
        s.emit(bits)
        return

    if '--sweep' in sys.argv:
        print('\n== structured patterns ==')
        pats = {'all1': lambda n: [1] * n, 'all0': lambda n: [0] * n,
                'alt10': lambda n: [k % 2 for k in range(n)],
                'alt1100': lambda n: [(k // 2) % 2 for k in range(n)],
                'one1': lambda n: [1] + [0] * (n - 1),
                'sparse8': lambda n: [1 if k % 8 == 0 else 0 for k in range(n)]}
        bestall = 0
        for name, f in pats.items():
            for n in (8, 16, 24, 32, 48, 64, 96, 128, 192, 256):
                sc, hit = s.run(f(n))
                if hit is not None:
                    print(f'  *** {name} len {n}: SUCCESS at cycle {hit}')
                    s.emit(f(n)); return
                bestall = max(bestall, sc)
            print(f'  {name:<9} best score {bestall}/{len(s.cone)}')
        print('\n== exhaustive short inputs ==')
        for n in range(1, 21):
            for k in range(2 ** n):
                bits = [(k >> (n - 1 - j)) & 1 for j in range(n)]
                sc, hit = s.run(bits, tail=80)
                if hit is not None:
                    print(f'  *** len {n} value {k:0{n}b}: SUCCESS at cycle {hit}')
                    s.emit(bits); return
            print(f'  all {2**n} inputs of length {n} exhausted')
        return

    if '--random' in sys.argv:
        t0 = time.time(); n = 0; best = 0
        while True:
            n += 1
            bits = [random.randint(0, 1) for _ in range(random.choice([16, 32, 48, 64, 96]))]
            sc, hit = s.run(bits)
            if hit is not None:
                print(f'  *** SUCCESS at cycle {hit} after {n} tries')
                print('  input:', ''.join(map(str, bits)))
                s.emit(bits); return
            best = max(best, sc)
            if n % 200 == 0:
                print(f'  {n} tries, best {best}/{len(s.cone)}, {time.time()-t0:.0f}s')

    # default: hill climb
    cur = [random.randint(0, 1) for _ in range(L)]
    score, hit = s.run(cur)
    print(f'\n== hill climb, length {L}, start score {score}/{len(s.cone)} ==')
    t0 = time.time(); it = 0; stall = 0
    while True:
        it += 1
        cand = cur[:]
        for _ in range(random.choice([1, 1, 1, 2, 3])):
            cand[random.randrange(L)] ^= 1
        sc, hit = s.run(cand)
        if hit is not None:
            print(f'  *** SUCCESS at cycle {hit}')
            print('  input:', ''.join(map(str, cand)))
            s.emit(cand); return
        if sc >= score:
            if sc > score:
                stall = 0
            score, cur = sc, cand
        stall += 1
        if stall > 3000:                     # restart from scratch
            cur = [random.randint(0, 1) for _ in range(L)]
            score, _ = s.run(cur); stall = 0
            print(f'  restart at it{it}')
        if it % 500 == 0:
            print(f'  it{it:>7} score {score}/{len(s.cone)}  [{time.time()-t0:.0f}s]')


if __name__ == '__main__':
    main()
