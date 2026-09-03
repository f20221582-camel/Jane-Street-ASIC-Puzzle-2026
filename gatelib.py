"""Boolean function of every sky130_fd_sc_hd cell used in this design.

Naming convention:
  aXY..o  = AND groups of size X, Y ... OR'd together, non-inverting output X
  aXY..oi = same, inverted output Y
  oXY..a  = OR groups AND'd together
  b in a name = that input is inverted (pin has _N suffix)
"""

def _and(*v): 
    r = 1
    for x in v: r &= x
    return r

def _or(*v):
    r = 0
    for x in v: r |= x
    return r

# each entry: cellbase -> (output_pin, lambda p: value)   p = dict of input pins
G = {
 'inv':      ('Y', lambda p: 1 - p['A']),
 'buf':      ('X', lambda p: p['A']),
 'clkbuf':   ('X', lambda p: p['A']),
 'dlymetal6s2s': ('X', lambda p: p['A']),

 'and2':     ('X', lambda p: _and(p['A'], p['B'])),
 'and2b':    ('X', lambda p: _and(1-p['A_N'], p['B'])),
 'and3':     ('X', lambda p: _and(p['A'], p['B'], p['C'])),
 'and3b':    ('X', lambda p: _and(1-p['A_N'], p['B'], p['C'])),
 'and4':     ('X', lambda p: _and(p['A'], p['B'], p['C'], p['D'])),
 'and4b':    ('X', lambda p: _and(1-p['A_N'], p['B'], p['C'], p['D'])),
 'and4bb':   ('X', lambda p: _and(1-p['A_N'], 1-p['B_N'], p['C'], p['D'])),

 'or2':      ('X', lambda p: _or(p['A'], p['B'])),
 'or2b':     ('X', lambda p: _or(p['A'], 1-p['B_N'])),
 'or3':      ('X', lambda p: _or(p['A'], p['B'], p['C'])),
 'or3b':     ('X', lambda p: _or(p['A'], p['B'], 1-p['C_N'])),
 'or4':      ('X', lambda p: _or(p['A'], p['B'], p['C'], p['D'])),
 'or4b':     ('X', lambda p: _or(p['A'], p['B'], p['C'], 1-p['D_N'])),
 'or4bb':    ('X', lambda p: _or(p['A'], p['B'], 1-p['C_N'], 1-p['D_N'])),

 'nand2':    ('Y', lambda p: 1-_and(p['A'], p['B'])),
 'nand2b':   ('Y', lambda p: 1-_and(1-p['A_N'], p['B'])),
 'nand3':    ('Y', lambda p: 1-_and(p['A'], p['B'], p['C'])),
 'nand3b':   ('Y', lambda p: 1-_and(1-p['A_N'], p['B'], p['C'])),
 'nand4':    ('Y', lambda p: 1-_and(p['A'], p['B'], p['C'], p['D'])),
 'nor2':     ('Y', lambda p: 1-_or(p['A'], p['B'])),
 'nor3':     ('Y', lambda p: 1-_or(p['A'], p['B'], p['C'])),
 'nor3b':    ('Y', lambda p: 1-_or(p['A'], p['B'], 1-p['C_N'])),
 'nor4':     ('Y', lambda p: 1-_or(p['A'], p['B'], p['C'], p['D'])),
 'nor4b':    ('Y', lambda p: 1-_or(p['A'], p['B'], p['C'], 1-p['D_N'])),

 'xor2':     ('X', lambda p: p['A'] ^ p['B']),
 'xnor2':    ('Y', lambda p: 1 - (p['A'] ^ p['B'])),
 'mux2':     ('X', lambda p: p['A1'] if p['S'] else p['A0']),
 'mux2i':    ('Y', lambda p: 1 - (p['A1'] if p['S'] else p['A0'])),

 # AND-OR family
 'a21o':     ('X', lambda p: _or(_and(p['A1'], p['A2']), p['B1'])),
 'a21oi':    ('Y', lambda p: 1-_or(_and(p['A1'], p['A2']), p['B1'])),
 'a21bo':    ('X', lambda p: _or(_and(p['A1'], p['A2']), 1-p['B1_N'])),
 'a21boi':   ('Y', lambda p: 1-_or(_and(p['A1'], p['A2']), 1-p['B1_N'])),
 'a22o':     ('X', lambda p: _or(_and(p['A1'], p['A2']), _and(p['B1'], p['B2']))),
 'a22oi':    ('Y', lambda p: 1-_or(_and(p['A1'], p['A2']), _and(p['B1'], p['B2']))),
 'a31o':     ('X', lambda p: _or(_and(p['A1'], p['A2'], p['A3']), p['B1'])),
 'a31oi':    ('Y', lambda p: 1-_or(_and(p['A1'], p['A2'], p['A3']), p['B1'])),
 'a32o':     ('X', lambda p: _or(_and(p['A1'], p['A2'], p['A3']),
                                 _and(p['B1'], p['B2']))),
 'a41oi':    ('Y', lambda p: 1-_or(_and(p['A1'], p['A2'], p['A3'], p['A4']), p['B1'])),
 'a211o':    ('X', lambda p: _or(_and(p['A1'], p['A2']), p['B1'], p['C1'])),
 'a211oi':   ('Y', lambda p: 1-_or(_and(p['A1'], p['A2']), p['B1'], p['C1'])),
 'a2111oi':  ('Y', lambda p: 1-_or(_and(p['A1'], p['A2']), p['B1'], p['C1'], p['D1'])),
 'a221o':    ('X', lambda p: _or(_and(p['A1'], p['A2']), _and(p['B1'], p['B2']), p['C1'])),
 'a221oi':   ('Y', lambda p: 1-_or(_and(p['A1'], p['A2']), _and(p['B1'], p['B2']), p['C1'])),
 'a311o':    ('X', lambda p: _or(_and(p['A1'], p['A2'], p['A3']), p['B1'], p['C1'])),

 # OR-AND family
 'o21a':     ('X', lambda p: _and(_or(p['A1'], p['A2']), p['B1'])),
 'o21ai':    ('Y', lambda p: 1-_and(_or(p['A1'], p['A2']), p['B1'])),
 'o21ba':    ('X', lambda p: _and(_or(p['A1'], p['A2']), 1-p['B1_N'])),
 'o21bai':   ('Y', lambda p: 1-_and(_or(p['A1'], p['A2']), 1-p['B1_N'])),
 'o22a':     ('X', lambda p: _and(_or(p['A1'], p['A2']), _or(p['B1'], p['B2']))),
 'o22ai':    ('Y', lambda p: 1-_and(_or(p['A1'], p['A2']), _or(p['B1'], p['B2']))),
 'o31a':     ('X', lambda p: _and(_or(p['A1'], p['A2'], p['A3']), p['B1'])),
 'o31ai':    ('Y', lambda p: 1-_and(_or(p['A1'], p['A2'], p['A3']), p['B1'])),
 'o32a':     ('X', lambda p: _and(_or(p['A1'], p['A2'], p['A3']), _or(p['B1'], p['B2']))),
 'o32ai':    ('Y', lambda p: 1-_and(_or(p['A1'], p['A2'], p['A3']), _or(p['B1'], p['B2']))),
 'o211a':    ('X', lambda p: _and(_or(p['A1'], p['A2']), p['B1'], p['C1'])),
 'o211ai':   ('Y', lambda p: 1-_and(_or(p['A1'], p['A2']), p['B1'], p['C1'])),
 'o221a':    ('X', lambda p: _and(_or(p['A1'], p['A2']), _or(p['B1'], p['B2']), p['C1'])),
 'o311a':    ('X', lambda p: _and(_or(p['A1'], p['A2'], p['A3']), p['B1'], p['C1'])),
 # UNVERIFIED: only 1 instance in the design. see notes.
 'o2bb2a':   ('X', lambda p: _and(_or(1-p['A1_N'], 1-p['A2_N']), _or(p['B1'], p['B2']))),
}

SEQ = {'dfrtp', 'dfstp', 'dfxtp'}     # flip-flops
PHYS = {'tapvpwrvgnd', 'decap', 'fill', 'diode'}   # no logic
