# Jane Street ASIC Puzzle 2026

Reverse-engineering a chip layout back into a circuit, using nothing but Python's standard library and one SAT solver.

You get a `.gds` file. That's a binary dump of physical shapes on silicon. No netlist, no schematic, no idea what the circuit does. The task is to recover the placement (DEF), the gate-level netlist, and work out what the thing actually computes.

> **Spoiler warning.** The answer is below. Stop reading if you want to solve [the puzzle]([https://github.com/janestreet/asic-puzzle-2026]) yourself.

---

## The answer

```
(* TWO STARS *)
```

15 bytes emitted on `O[7:0]` after `success` fires. It's an OCaml comment, which is a nice touch given Jane Street's house language.

## What the chip turned out to be

**A hardware validator for an 11x11 Star Battle puzzle** (also called Two Not Touch).

A base-11 counter runs for 121 cycles while grid cells shift in one per clock on `I`. Logic accumulates row counts, column counts and adjacency as they arrive. At cycle 120 the counter finishes, and at cycle 122 a 47-gate reduction produces `success`. A sticky latch then releases a 4-bit counter that streams the message out one byte per cycle.

The grid that satisfies it:

```
. . . . . . . * . * .
* . . . . * . . . . .
. . . . . . . * . * .
* . * . . . . . . . .
. . . . * . * . . . .
. . * . . . . . * . .
. . . . * . . . . . *
. * . . . . * . . . .
. . . * . . . . . . *
. . . . . * . . * . .
. * . * . . . . . . .
```

Two stars per row, two per column, none touching. Fed in as 121 bits:

```
0000000101010000100000000000010101010000000000001010000001000001000000100000101000010000000100000010000010010001010000000
```

## Easter egg

**PER ARENAM AD ASTRA**, spelled in Morse code below the die at y = -52.72um.

36 cells sit in a row outside the die area, in two widths that are in an exact 3:1 ratio. A dash in Morse is exactly 3x a dot. Reading narrow as dot and wide as dash, then measuring the horizontal gaps, every gap came out as exactly 1, 3 or 7 units of 1.380um. Those are the three legal Morse gap lengths.

*Through the sand to the stars.* A play on **per aspera ad astra**, sand being where silicon comes from.

---

## The pipeline

| Script | What it does |
|---|---|
| `gds_peek.py` | Inventory: layers, cell definitions, placements, text labels |
| `gds_census.py` | Cell counts, hierarchy flattening, repeated-pattern detection in cell rows |
| `gds_blocks.py` | Per-module census, floorplan map, port coordinates |
| `gds_cellinfo.py` | What's inside one cell definition: size, shapes by layer |
| `morse_decode.py` | Decodes the off-die annotation from cell positions and widths |
| `gds_flatten.py` | Paths and polygons to rectangles, hierarchy to absolute coordinates |
| `gds_netlist.py` | Union-find connectivity, pin attachment, Verilog output |
| `gds_def.py` | Writes the DEF placement file |
| `gatelib.py` | Boolean function of every sky130 cell used in the design |
| `sim.py` | Gate-level simulator |
| `solve.py` | Input search: random, structured, hill climbing (this one didn't work) |
| `bmc.py` | SAT-based bounded model checking (this one did) |

## Requirements

Python 3.8 or later. Everything is standard library except `bmc.py`:

```bash
pip install python-sat
```

## Reproducing it

Run them in this order.

**1. Look at the file**

```bash
python3 gds_peek.py puzzle.gds
python3 gds_census.py puzzle.gds --rows
python3 gds_blocks.py puzzle.gds
```

**2. Chase the two mystery cells**

```bash
python3 gds_cellinfo.py puzzle.gds INTERNAL_3 INTERNAL_7 VIA_M1M2_PR
python3 morse_decode.py puzzle.gds
```

**3. Extract the netlist and DEF**

```bash
python3 gds_flatten.py puzzle.gds
python3 gds_netlist.py puzzle_flat.pkl
python3 gds_def.py puzzle_flat.pkl puzzle_nets.pkl --out puzzle.def
```

Produces `puzzle.v` (1,618 instances, 728 wires) and `puzzle.def` (1,618 components, 739 nets, 104 rows).

**4. Simulate**

```bash
python3 sim.py puzzle_nets.pkl --probe
```

**5. Solve for the input**

```bash
python3 bmc.py puzzle_nets.pkl --K 128 --succ success --inputs I --hold enable
```

Takes about 3 seconds. Prints the input bits, verifies them against the simulator, and decodes the output bytes.

## You'll need the warm-up files

The `warmup/` folder from Jane Street's original repo isn't included here. Every stage was validated against it, and I'd strongly recommend doing the same if you're rerunning any of this:

```bash
python3 gds_flatten.py warmup.gds
python3 gds_netlist.py warmup_flat.pkl
python3 sim.py warmup_nets.pkl --selftest
python3 bmc.py warmup_nets.pkl --K 12 --succ S --inputs A B --hold en
```

The self-test should print:

```
A=248 B=248  A+B= 496   S=1   <-- SUCCESS
A=255 B=241  A+B= 496   S=1   <-- SUCCESS
A=200 B= 40  A+B= 240   S=0
```

That one test validates the GDS parser, the polygon decomposition, the coordinate transforms, the connectivity extraction, the gate library and the simulator all at once. If it ever stops passing, something upstream broke.

## Numbers

| | warm-up | puzzle |
|---|---|---|
| Die | 100 x 100 um | 200 x 300 um |
| Flattened rectangles | 17,716 | 130,861 |
| Cell instances | 1,099 | 9,875 |
| Logic cells | 79 | 722 |
| Flip-flops | 16 | 92 |
| Nets | 335 | 2,626 |
| Wires in netlist | 80 (theirs: 78) | 728 |
| Nets with >1 driver | 0 | 0 |

## Things that went wrong

**Polygons reduced to bounding boxes.** A thin li1 wire that snakes across a cell has a bounding box covering nearly the whole cell. Treating that box as solid metal shorted every pin together, and the shorts spread between cells through the power rails until the entire chip was one net of 9,995 shapes. Found it by asking why there was a 7.12um wire inside a 2.72um-tall cell. Fixed with a scanline decomposition.

**IBM floating point.** GDSII predates IEEE 754 and uses base-16 excess-64 reals. Decoding them with `struct.unpack('>d')` produced a chip several metres wide.

**Pinning the clock in the SAT encoder.** There are 32 clock buffers in the netlist and they're real combinational gates, so fixing `clk` to 0 forced a whole tree of nets to fixed values. Made the puzzle look provably unsolvable.

**Forcing the reset-less flops to start at 0.** `dfxtp` cells have no reset or set pin, so their power-up value is genuinely unknown and has to be left free for the solver.

The last two both produced UNSAT at every depth in under two seconds, which looks exactly like a real impossibility result. Only the warm-up regression caught them.

## Full writeup

[PuzzleWriteup.md](PuzzleWriteup.md) has the whole thing: the three wrong hypotheses about the mystery cells, how the Morse decode worked, the connectivity extraction in detail, and how the base-11 counter gave away the 11x11 grid.

## One thing I didn't finish

The chip enforces more than the three Star Battle rules I identified. I generated six other grids satisfying 2-per-row, 2-per-column and no-touching, and the circuit rejects all of them. Only the recovered grid fires `success`.

So there's a further constraint hardwired in, almost certainly the region rule, which is what gives a real Star Battle puzzle a unique solution. It should be recoverable by feeding single-star probe grids and watching which cells the constraint logic groups together. I ran out of time.
