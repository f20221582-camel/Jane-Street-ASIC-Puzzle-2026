# Jane Street ASIC Puzzle 2026 — solved with pure Python

Reverse-engineering a chip layout back into a circuit, using nothing but the Python standard
library and one SAT solver. No KLayout, no Magic, no Calibre.

> **Spoiler warning.** This repo contains the full solution. If you want to solve
> [the puzzle](https://github.com/janestreet/asic-puzzle-2026) yourself, stop here.

---

## The answer

```
(* TWO STARS *)
```

Fifteen bytes emitted on `O[7:0]`, starting at clock cycle 122. It's an OCaml comment, which
is a nice touch given whose puzzle it is.

## What the chip turned out to be

**A hardware validator for an 11×11 Star Battle puzzle** (also called Two Not Touch).

A base-11 counter runs for 121 cycles while grid cells shift in one per clock on `I`. Logic
accumulates row counts, column counts and adjacency as they arrive. At cycle 120 the counter
hits its terminal state, and at cycle 122 a 47-gate reduction produces `success`. A sticky
latch then releases a 4-bit counter that streams the message out one ASCII byte per cycle.

The winning grid:

```
. . . . . . . ★ . ★ .        row sums: 2 2 2 2 2 2 2 2 2 2 2
★ . . . . ★ . . . . .        col sums: 2 2 2 2 2 2 2 2 2 2 2
. . . . . . . ★ . ★ .        touching pairs: 0
★ . ★ . . . . . . . .
. . . . ★ . ★ . . . .
. . ★ . . . . . ★ . .
. . . . ★ . . . . . ★
. ★ . . . . ★ . . . .
. . . ★ . . . . . . ★
. . . . . ★ . . ★ . .
. ★ . ★ . . . . . . .
```

As 121 bits, fed one per clock on `I` with `enable` high after reset:

```
0000000101010000100000000000010101010000000000001010000001000001000000100000101000010000000100000010000010010001010000000
```

---

## Reproduce it

```bash
pip install python-sat          # only needed for the final step

python3 gds_flatten.py puzzle.gds          # geometry -> flat rectangles
python3 gds_netlist.py puzzle_flat.pkl     # rectangles -> netlist
python3 gds_def.py puzzle_flat.pkl puzzle_nets.pkl --out puzzle.def
python3 sim.py puzzle_nets.pkl --probe     # explore the circuit
python3 bmc.py puzzle_nets.pkl --K 123 --succ success --inputs I --hold enable
```

Or just `./run_all.sh`, which does the whole thing including the warm-up validation.

**Validate against ground truth first.** The warm-up ships with its real netlist and DEF, so
every stage can be checked before you trust it on the puzzle:

```bash
python3 gds_flatten.py warmup.gds
python3 gds_netlist.py warmup_flat.pkl
python3 sim.py warmup_nets.pkl --selftest    # must print S=1 for 248+248 and 255+241
python3 bmc.py warmup_nets.pkl --K 12 --succ S --inputs A B --hold en
```

The self-test asserts when `A + B == 496`, which is the warm-up's documented behaviour. If
that ever stops passing, something upstream broke.

---

## The pipeline

| Script | What it does |
|---|---|
| `gds_peek.py` | Dumps everything readable in a GDS: layers, cell definitions, placements, text labels |
| `gds_census.py` | Cell counts, hierarchy flattening, repeating-pattern detection across cell rows |
| `gds_blocks.py` | Per-module census, floorplan map, port coordinates |
| `gds_cellinfo.py` | What's actually inside one cell definition — size, shapes by layer, verdict |
| `morse_decode.py` | Decodes the off-die annotation from cell positions and widths |
| `gds_flatten.py` | Paths → rectangles, polygons → rectangles, hierarchy → absolute coordinates |
| `gds_netlist.py` | Union-find connectivity, pin attachment, Verilog output |
| `gds_def.py` | Writes the DEF placement file |
| `gatelib.py` | Boolean function of every sky130 cell used in the design |
| `sim.py` | Gate-level simulator |
| `solve.py` | Input search by random / structured / hill-climbing (this one **didn't work** — see below) |
| `bmc.py` | SAT-based bounded model checking (this one did) |

All pure standard library except `bmc.py`, which needs `python-sat`.

---

## How it works, briefly

**A GDS file contains only shapes.** It never says "wire 42 connects gate 17 to gate 23".
Connectivity exists implicitly, as metal rectangles that happen to touch. Two rules govern
everything:

- metal on the **same** layer connects by overlapping
- metal on **different** layers connects only through a via

So: convert every shape to rectangles, move them all into one coordinate system, then
union-find over overlaps and via bridges. Cell pin names come free — sky130 cells carry their
pin shapes on layer `/16` and pin labels on `/5` at the same coordinates, so no LEF file is
needed.

That gives a netlist. Then write out every cell's Boolean function, simulate, and search for
the input that asserts `success`.

---

## Things that went wrong

**The bounding-box bug.** The first version reduced each polygon to its bounding box. Layout
shapes aren't rectangles — a `li1` route snaking across a cell has a bounding box covering
the whole cell, which shorted every pin together, and the shorts spread through power rails
until the entire chip was one net of 9,995 shapes. Found it by asking why there was a 7.12 µm
wire inside a 2.72 µm-tall cell. Fixed with scanline polygon decomposition.

**Search doesn't work here.** Random and hill-climbing searches over input sequences
plateaued at 31/47 on the scoring heuristic and never moved. They were hunting 16- to 96-bit
inputs in a space SAT later *proved* contains no solution — the minimum viable input is 122
cycles.

**Two SAT encoding bugs** made the puzzle look provably impossible. Pinning `clk` to 0 broke
the clock-buffer tree, and forcing the reset-less `dfxtp` flops to start at 0 over-constrained
the initial state (they have no reset pin, so their power-up value is genuinely unknown). Both
were caught only because the warm-up regression had to keep passing after every change.

---

## Easter egg

**PER ARENAM AD ASTRA**, in Morse code, spelled out at `y = -52.72 µm` — below the die,
outside the circuit, connected to nothing.

36 cells in a single row, two types. `INTERNAL_3` is 1.380 µm wide, `INTERNAL_7` is 4.140 µm.
Exactly a **3:1 ratio**, which is the defining ratio of Morse — a dash is three times a dot.
Reading narrow as dot and wide as dash, then measuring the horizontal gaps between cells,
every gap came out as exactly **1, 3 or 7** units of 1.380 µm. Those are the three legal Morse
gap lengths: within a letter, between letters, between words.

```
gap histogram (in units): [(1, 20), (3, 12), (7, 3)]
```

Three word-gaps means four words, and four words came out. *Through the sand to the stars* —
a play on *per aspera ad astra*, with **sand** swapped in, because that's where silicon comes
from.

---

## Known gap

The chip enforces **more** than the three rules I identified. I generated six other grids
satisfying 2-per-row, 2-per-column and no-touching, and the circuit rejects every one — only
the recovered grid fires `success`.

Almost certainly the **region constraint**, which is what gives a real Star Battle puzzle a
unique solution. It'd be hardwired into the constraint logic around x ≈ 75–92 µm. Should be
recoverable by feeding single-star probe grids and watching which cells the logic groups
together. I ran out of time.

---

## Repo layout

```
puzzle.gds                     the puzzle              (Jane Street)
warmup.gds                     warm-up layout          (Jane Street)
01_netlist.v                   warm-up ground truth    (Jane Street)
03_post_place_and_route.def    warm-up ground truth    (Jane Street)
example_inputs.vcd             sample inputs           (Jane Street)

gds_*.py  sim.py  solve.py  bmc.py  gatelib.py        the toolchain
morse_decode.py                                        easter egg decoder
run_all.sh                                             one-command reproduce

results/puzzle.v               extracted netlist    (1,618 instances, 728 wires)
results/puzzle.def             extracted placement  (1,618 components, 739 nets, 104 rows)
results/answer.txt             the 121-bit input and the recovered string

PuzzleWriteup.md               full writeup — approach, dead ends, findings
```

Intermediate `.pkl` files are generated by the scripts and gitignored.

---

## Credits

Puzzle by [Jane Street](https://github.com/janestreet/asic-puzzle-2026). The five source
files above are theirs and are included so the pipeline is runnable end to end.

Standard cells are [SkyWater sky130](https://github.com/google/skywater-pdk), Apache 2.0.

Everything else here is mine, MIT licensed. Full account of how it was done in
[`PuzzleWriteup.md`](PuzzleWriteup.md).
