# Reversing the Jane Street ASIC puzzle with pure Python

I'm an engineering student and I do a lot of puzzles, so when I saw this one I figured I'd try it properly rather than reaching for KLayout. Everything below is standard library Python plus one SAT solver at the very end. No Magic, no Calibre, no KLayout, nothing.

Answer: **TWO STARS**

---

## Starting point

You get `puzzle.gds` and a `warmup/` folder. The warm-up has the same design flow but for a much simpler circuit, and critically it ships with the answers at every stage: source Verilog, gate netlist, DEF, final GDS.

I decided early that I'd build every tool against the warm-up first, and only point it at the puzzle once it reproduced known-correct output. This was easily the best decision I made. Two of my bugs would have silently produced wrong answers otherwise, and one of them would have convinced me the puzzle was unsolvable.

## Step 1: reading the file at all

GDSII is a stream of records. Each record starts with its own length, then a type byte and a data type byte, then the payload. Because the length is in the header you can walk the whole file without understanding any of it, which makes the reader about nine lines.

The one thing that actually got me was the floating point. GDSII predates IEEE 754 and uses IBM System/360 format: 7-bit exponent, base **16**, excess-64. I decoded it with `struct.unpack('>d')` first and got a chip that was apparently several metres across. Took me longer than I want to admit to figure out why.

I wrote a small script (`gds_peek.py`) that just dumps everything readable: layers, cell definitions, cell placements, text labels. Ten minutes of work and it changed my whole plan.

Two things it showed:

**Cell names survived.** `sky130_fd_sc_hd__nand2_2`, `sky130_fd_sc_hd__dfrtp_2`, and so on. "Names removed" meant net names and instance names, not cell types. This makes sense in hindsight since the library cells are read from disk by name and the flow can't rename them. I had a whole plan for identifying cells by hashing their geometry against the public sky130 GDS, and this killed it immediately. Saved me a day.

**The port list**, on layer 70/5 (met3 labels): `I`, `O[0]` through `O[7]`, `clk`, `enable`, `rst_n`, `success`.

`I` has no brackets and appears once. So it's one wire. One-bit input plus a clock plus an enable means the answer is a sequence of bits fed in over time. The warm-up confirmed the idiom: two serial inputs, 16 flip-flops as two 8-bit shift registers, output goes high when A + B == 496.

## Step 2: being wrong three times

There were two cells with obfuscated names, `INTERNAL_3` placed 21 times and `INTERNAL_7` placed 15 times. 21 + 15 = 36 and I got excited, because 36 could be a 6x6 grid and that would mean I only had to reverse two small modules instead of the whole chip.

**Hypothesis 1: they're modules.** I wrote a script to find where each block sits and what's inside it. Both contain zero cell instances. Not modules. Dead.

But the same run told me the design is completely flat: 722 logic cells, 92 flip-flops, all in one top cell. That mattered later.

**Hypothesis 2: they're via stamps**, like the nine `VIA_*` cells which are also pure geometry pressed thousands of times. Wrote another script to dump what's inside a cell definition. A real via is 0.32um across and holds met1 + a cut + met2. These are 1.380 x 2.720um and 4.140 x 2.720um, holding one rectangle on layer 200/0, which isn't a sky130 layer at all. Dead.

**Hypothesis 3: they're redacted logic cells.** Because 2.720um is exactly the standard cell row height and 1.380 / 4.140 are exactly 3 and 9 placement sites. Cell shaped, cell sized, contents blanked. Seemed obvious.

Then I looked at where they actually sit: y = -52,720nm. Negative. The die runs from y=0 to 300um and the real circuitry starts at 10.88um. All 36 of them are parked below the chip, outside the die, in one line, touching nothing. Dead.

Three wrong guesses in a row, each killed in a few minutes because each one was stated in a way I could test. I think that's actually the main technique here more than any particular script.

## Step 3: the Morse thing

So what are they. I noticed the widths: 1.380 and 4.140, which is exactly 3.0x. And I do a lot of puzzles, so "two symbols in a 1:3 length ratio, in a line" pinged Morse immediately. A dash is exactly three times a dot, that's the defining ratio of the whole encoding.

But the symbol order alone isn't enough. `.-` is A and `.` `-` is E T. The information is in the gaps: 1 unit inside a letter, 3 between letters, 7 between words.

So I went back to the GDS, read each cell's x position and width, computed the gap to the next one, divided by 1.380um.

Every single gap came out as exactly 1, 3 or 7. Twenty at 1 unit, twelve at 3, three at 7. Nothing in between, no rounding fudge. Three word gaps means four words and four words came out:

> **PER ARENAM AD ASTRA**

"Through the sand to the stars." It's a play on *per aspera ad astra*, through hardships to the stars, with *aspera* swapped for *arenam*, sand. Because silicon comes from sand. That's a genuinely good joke and I sat there grinning at my laptop for a bit.

Before trusting the decoder I built a fake GDS that encoded "HI JS" in Morse using the same cell widths and spacing rules, and confirmed it round-tripped. Seemed worth checking given I was pattern matching on 36 symbols and hoping for Latin.

## Step 4: actually extracting the netlist

This is the real work. A GDS contains only shapes. It never says "wire 42 connects gate 17 to gate 23". Connectivity exists implicitly, as metal rectangles that happen to touch.

The rule is simple: metal on the same layer connects by overlapping, metal on different layers connects only through a via.

So the plan was: turn everything into rectangles, put them all in one coordinate system, then union-find.

**Paths.** About 7,196 shapes are PATH records, which store a centreline and a width, not a rectangle. If you only read the endpoints then every routed wire in the design is infinitely thin and nothing touches anything. You also have to handle end extensions correctly (PATHTYPE 0, 1, 2, 4) or wires come up short of their vias and nets split silently.

**Flattening.** Shapes inside a cell are drawn relative to that cell's own origin. The same cell is placed dozens of times. The GDS transform order is mirror about x, then rotate, then translate, and the order genuinely matters. Take (10,5): mirror then rotate 90 gives (5,10), rotate then mirror gives (-5,-10). Completely different places.

**Then I hit the bug that broke everything.**

My first version reduced each polygon to its bounding box, because I assumed layout shapes were mostly rectangles anyway. They aren't. I ran the extraction and got 5 nets for the entire warm-up chip, one of them containing 9,995 shapes, and a final netlist with exactly one wire in it.

I found it by dumping the largest shape per layer and asking whether the numbers were physically sensible:

```
(67,20) li1   7.12 x 2.20 um   inside a single standard cell
```

A standard cell is 2.72um tall. How is there a 7.12um wire inside it. There isn't. What's actually there is a thin li1 route that snakes across the cell, and its bounding box is a solid block covering nearly the whole thing. That block overlapped every other pin in the cell, so every pin shorted together, and then the shorts spread between cells through the power rails until the entire chip was one net.

Fixed it with a scanline decomposition: slice the polygon at every vertex height, and within each horizontal band work out which x intervals are actually inside using even-odd. L-shape becomes 2 rectangles, U-shape becomes 3, plain rectangle stays 1.

After that: 335 nets on the warm-up, all 8 ports named, zero nets with two drivers.

**Union-find with a spatial hash.** Comparing 130,861 rectangles pairwise is 17 billion tests. Bucketing the die into 2um squares and only comparing rectangles that share a bucket brought the whole puzzle extraction down to under a second.

**Pin names for free.** Every sky130 cell carries its pin shapes on layer /16 and its pin labels on /5 at the same coordinates. So you can look up which net is at a pin's location and read its name straight out of the geometry. Never needed a LEF file.

Result: 1,618 instances, 728 wires, 2,626 nets total (most of which are floating fill metal that touches no pin).

**Validation.** Cell type histogram from my netlist vs `01_netlist.v`, matched exactly, all 18 types with identical counts. 80 wires vs their 78. Zero double-driven nets.

## Step 5: simulating it

A netlist is a wiring diagram. To find out what a circuit does you have to run it.

I wrote out the Boolean function of all 65 sky130 cell types by hand. The names encode their own function once you see the pattern: `a2111oi` means AND groups of size 2,1,1,1, OR'd together, inverted output, so `Y = !((A1&A2) | B1 | C1 | D1)`.

Then a two-phase simulator: evaluate every combinational gate, then commit all 92 flip-flops simultaneously. The "simultaneously" part matters a lot. Update flops one at a time and a shift register collapses into a single stage.

Small things that bit me: via cells crashed the name parser because they have no `__` in them. Tie cells (`conb_1`) have two outputs and didn't fit my one-output table, and that also made 8 downstream gates look like they were in a loop. Ten gates were in a genuine combinational feedback loop, which I handled by iterating to a fixed point, then checked where they physically sat (all in the output generator, nowhere near `success`).

Then the test that made everything worth it. The warm-up is documented to assert when A + B == 496:

```
A=248 B=248  A+B= 496   S=1
A=255 B=241  A+B= 496   S=1
A=200 B= 40  A+B= 240   S=0
A=100 B=100  A+B= 200   S=0
```

Correct for both cases that should fire and wrong for none. Every stage of the pipeline had to be right simultaneously for that to happen.

## Step 6: finding the input, badly

I tried structured patterns, exhaustive short inputs, and hill climbing with a score based on how many nodes in the success cone were satisfied. Left three terminal tabs running for half an hour.

Best score plateaued at 31 out of 47 and never moved. 14,200 random tries, nothing. The exhaustive sweep was going to need 36 hours to reach 20-bit inputs.

## Step 7: finding it properly

Bounded model checking. Make one copy of the whole circuit per clock cycle, wire cycle t's flip-flop outputs into cycle t+1's inputs, fix cycle 0 to the reset state, assert `success` at some cycle, and hand the whole thing to a SAT solver as CNF.

The key property is that SAT is *complete*. If it says UNSAT for 96 cycles, that's a proof that no 96-cycle input works. No amount of random sampling gives you that.

First run said UNSAT at 24, 32, 48, 64 and 96 cycles, all within seconds. Suspiciously fast and suspiciously uniform, which usually means you've over-constrained something rather than found a real impossibility. Two bugs:

1. I'd pinned `clk` to 0, reasoning that the simulator handles clocking separately so the value doesn't matter. But there are 32 clock buffers in the netlist and they're real combinational gates. Pinning the clock forced a whole tree of nets to fixed values.

2. I'd forced the reset-less flops (`dfxtp`, no reset or set pin) to start at 0. Their power-up value is genuinely unknown and has to be left free.

Both were caught because I re-ran the warm-up regression after every change. Without that I'd have concluded the netlist was broken and gone back to redo step 4.

Fixed:

```
K = 112  ->  UNSAT
K = 122  ->  UNSAT
K = 123  ->  SAT, success first true at cycle 122
```

So the minimum is 122 cycles and every shorter search I'd run was hunting in a space that provably contained no solution.

## Step 8: what the machine actually is

I had the answer but not the understanding, so I kept going.

Tested whether the flip-flop dependency graph was symmetric, which it would be for a cellular automaton. 11%. Not that. Tested whether the state transition was linear over GF(2), which would make it an LFSR. 1 out of 60. Not that either.

Then I intersected the dependency sets of all 52 array flip-flops and found they **all** depend on one particular flop. Followed it into a block on the left side of the die: 10 flops, fed by `enable`, never by `I`. Autonomous.

At this point I stopped analysing and just printed its state every cycle as a number:

```
t=0   low=1  high=0
t=1   low=2  high=0
...
t=9   low=10 high=0
t=10  low=0  high=1
...
t=120 low=0  high=0  done=1
```

Base-11 counter. Terminal at cycle 120. **11 x 11 = 121.**

So `I` isn't a bit string, it's an 11x11 grid shifted in one cell per clock. I reshaped my 121 solution bits into a grid:

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

Every row sums to 2. Every column sums to 2. Zero pairs of stars touching, including diagonally.

That's Star Battle, also called Two Not Touch. And the chip had been telling me the whole time, since the message it prints is `(* TWO STARS *)`.

The SAT solver never knew any of this. It got 480,000 Boolean clauses with no concept of grids or stars and returned a valid Star Battle solution, because that's what those clauses encode.

## One thing I found at the end

I generated six other grids that satisfy all three rules I'd identified (2 per row, 2 per column, no touching) and fed them in. The circuit rejects every one. Only the recovered grid fires `success`.

So the chip enforces something stricter than what I'd found, almost certainly the region constraint, hardwired into the logic. That's what makes a real Star Battle puzzle have a unique solution. I ran out of time before extracting the region map, but it should be recoverable by feeding single-star probe grids and seeing which cells the constraint logic groups together.

## Final answer

**TWO STARS**

The 121 input bits, fed one per clock on `I` with `enable` high after reset:

```
0000000101010000100000000000010101010000000000001010000001
0000010000001000001010000100000001000000100000100100010100
00000
```

`success` goes high at cycle 122. Keep clocking and `O[7:0]` streams out `(* TWO STARS *)`, one byte per cycle.

## Stuff I'd do differently

Check magnitudes earlier. The bounding box bug was findable in five minutes by asking "why is there a 7um wire inside a 2.72um cell". I lost an hour to it.

Reach for SAT sooner. I spent real time on hill climbing over a space that a solver proved empty in three seconds.

And when stuck on *meaning* rather than mechanism, stop doing graph theory and just simulate the thing and print numbers. The counter explained the entire design in about ten seconds of output after two failed structural analyses.
