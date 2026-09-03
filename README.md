# 🔬 Reversing the Jane Street ASIC Puzzle (2026) — Pure Python

> **Answer: TWO STARS**

The [Jane Street ASIC Puzzle (2026)](https://www.janestreet.com/puzzles/) ships a fabricated chip layout as a GDSII file and challenges you to figure out what the circuit does, then find the input that makes it say "success."

I reversed the entire chip — from raw polygons to a SAT-solved answer — using **nothing but standard-library Python and one SAT solver**. No KLayout, no Magic, no Calibre, no commercial EDA tools.

The chip turned out to be a hardware **Star Battle** (Two Not Touch) puzzle verifier built on the [SkyWater SKY130](https://github.com/google/skywater-pdk) open-source process, with a Morse-code Easter egg hidden in the physical layout.

---

## 📋 Table of Contents

- [The Challenge](#the-challenge)
- [What I Built](#what-i-built)
- [Pipeline Overview](#pipeline-overview)
- [Key Discoveries](#key-discoveries)
- [Repository Structure](#repository-structure)
- [Running the Code](#running-the-code)
- [The Solution](#the-solution)
- [Detailed Writeup](#detailed-writeup)

---

## The Challenge

You are given:
- `puzzle.gds` — A GDSII layout of an ASIC fabricated on the SKY130 process. All net names and instance names have been stripped.
- `warmup.gds` — A smaller warm-up chip with known answers at every stage, used to validate your tools.
- `example_inputs.vcd` — A VCD waveform showing the port interface.
- `01_netlist.v` and `03_post_place_and_route.def` — Warm-up reference files for validation.

Your goal: determine what input, fed serially on pin `I`, causes the `success` output to assert.

## What I Built

A complete GDS-to-solution pipeline in ~1,200 lines of Python:

| Script | Purpose |
|--------|---------|
| `gds_peek.py` | Dump every human-readable thing from a GDSII file (layers, cells, labels) |
| `gds_cellinfo.py` | Classify cell definitions (logic cell, via stamp, module, or mystery) |
| `gds_census.py` | Architecture census: cell histograms, row structure, bitslice mining |
| `gds_blocks.py` | Floorplan geography, per-module census, ASCII die map |
| `morse_decode.py` | Decode the off-die Morse-code Easter egg |
| `gds_flatten.py` | **Phase 1–2**: Read all shapes (including PATHs), flatten hierarchy to absolute coordinates |
| `gds_netlist.py` | **Phase 3–4**: Union-find net extraction with spatial hashing, pin attachment, Verilog emission |
| `gds_def.py` | **Phase 5**: Write a DEF placement file from extracted data |
| `gatelib.py` | Boolean function table for all 65 SKY130 cell types |
| `sim.py` | **Phase 6**: Gate-level two-phase simulator with topological ordering |
| `solve.py` | **Phase 6b–c**: Brute-force search (hill climbing, random, exhaustive) |
| `bmc.py` | **Phase 6d**: Bounded model checking — unrolls the circuit into SAT/CNF and solves |

## Pipeline Overview

```
puzzle.gds
    │
    ├─ gds_peek.py ──────────── reconnaissance (layers, cell names, port list)
    ├─ gds_cellinfo.py ──────── identify mystery cells (INTERNAL_3, INTERNAL_7)
    ├─ gds_census.py ────────── structural census (722 logic cells, 92 flip-flops)
    ├─ gds_blocks.py ────────── floorplan + module-level analysis
    ├─ morse_decode.py ──────── Easter egg: "PER ARENAM AD ASTRA" 🏛️
    │
    ├─ gds_flatten.py ───────── shapes → absolute rectangles (scanline decomposition)
    │       ↓ puzzle_flat.pkl
    ├─ gds_netlist.py ───────── union-find → 2,626 nets → Verilog netlist
    │       ↓ puzzle_nets.pkl
    │
    ├─ sim.py ───────────────── gate-level simulation (validates on warm-up: A+B=496 ✓)
    ├─ solve.py ─────────────── brute-force search (plateau at 31/47, abandoned)
    └─ bmc.py ───────────────── SAT solver: UNSAT ≤122, SAT at 123 → success at cycle 122
                                 ↓
                              "TWO STARS" — the answer is (* TWO STARS *)
```

## Key Discoveries

### 🏛️ The Morse Code Easter Egg
36 cells with obfuscated names (`INTERNAL_3`, `INTERNAL_7`) are parked outside the die boundary in a line. Their widths are in a 1:3 ratio — exactly dot:dash in Morse code. The gaps between them measure exactly 1, 3, or 7 units. Decoded message:

> **PER ARENAM AD ASTRA** — "Through the sand to the stars"

A play on *per aspera ad astra*, with *aspera* (hardships) replaced by *arenam* (sand) — because silicon comes from sand.

### ⭐ The Star Battle Grid
The circuit is a hardware verifier for an **11×11 Star Battle** puzzle:
- A base-11 counter clocks 121 cycles (11 × 11 = 121)
- Input bit `I` is shifted into an 11×11 grid, one cell per clock
- The circuit checks: 2 stars per row, 2 stars per column, no adjacent stars (including diagonals)
- Region constraints are hardwired into the logic, ensuring a unique solution

### 🧮 The Bounding Box Bug
My first extraction attempt reduced every polygon to its bounding box. An L-shaped li1 route inside a cell became a solid block that shorted every pin together, and then the shorts propagated through power rails until the entire chip was one net. Fixed with scanline decomposition using even-odd fill.

### 🔧 SAT vs. Brute Force
Hill climbing plateaued at 31/47 satisfied nodes. 14,200 random tries found nothing. The SAT solver proved in seconds that no input shorter than 123 cycles can work — the entire search space I'd explored was provably empty.

## Repository Structure

```
├── README.md                        # You are here
├── PuzzleWriteup.md                 # Detailed narrative writeup
│
├── puzzle.gds                       # 🎯 The main puzzle GDSII layout
├── warmup.gds                       # Warm-up chip (known answers)
├── example_inputs.vcd               # Example VCD waveform
├── 01_netlist.v                     # Warm-up reference netlist
├── 03_post_place_and_route.def      # Warm-up reference DEF
│
├── gds_peek.py                      # GDSII reconnaissance tool
├── gds_cellinfo.py                  # Cell definition inspector
├── gds_census.py                    # Architecture census + pattern mining
├── gds_blocks.py                    # Floorplan + module census
├── morse_decode.py                  # Morse code Easter egg decoder
│
├── gds_flatten.py                   # Phase 1–2: flatten hierarchy → rectangles
├── gds_netlist.py                   # Phase 3–4: net extraction → Verilog
├── gds_def.py                       # Phase 5: DEF placement export
│
├── gatelib.py                       # SKY130 cell Boolean function library
├── sim.py                           # Gate-level simulator
├── solve.py                         # Brute-force search (hill climb / random)
├── bmc.py                           # Bounded model checking (SAT solver)
│
└── .gitignore                       # Excludes caches and regenerable files
```

> **Note:** Intermediate files (`.pkl`, generated `.v`/`.def`, output `.txt` logs) are excluded via `.gitignore` — they're large and fully reproducible by running the scripts.

## Running the Code

### Prerequisites

- **Python 3.10+** (standard library only for everything except the SAT solver)
- **python-sat** (for `bmc.py` only):
  ```bash
  pip install python-sat
  ```

### Reproduce the Full Pipeline

```bash
# 1. Reconnaissance
python3 gds_peek.py puzzle.gds
python3 gds_census.py puzzle.gds
python3 gds_blocks.py puzzle.gds
python3 gds_cellinfo.py puzzle.gds INTERNAL_3 INTERNAL_7

# 2. Decode the Morse Easter egg
python3 morse_decode.py puzzle.gds

# 3. Extract the netlist (the real work)
python3 gds_flatten.py puzzle.gds --out puzzle_flat.pkl
python3 gds_netlist.py puzzle_flat.pkl

# 4. Validate on the warm-up
python3 gds_flatten.py warmup.gds --out warmup_flat.pkl
python3 gds_netlist.py warmup_flat.pkl
python3 sim.py warmup_nets.pkl --selftest

# 5. Solve with SAT (finds the answer in seconds)
python3 bmc.py puzzle_nets.pkl --K 123 --succ success --inputs I --hold enable
```

### Expected Output from BMC

```
  52 of 92 flops matter for success
  encoding 407 gates over 123 cycles
  480,000+ clauses, ~200,000 vars
  SAT
  I = 000000010101000010000000001010101...
  success first true at cycle 122
  SIMULATOR CHECK: success fired = True
  as text: (* TWO STARS *)
```

## The Solution

The 121 input bits, fed one per clock on `I` with `enable` high after reset:

```
0000000101010000100000000000010101010000000000001010000001
0000010000001000001010000100000001000000100000100100010100
00000
```

Reshaped as an 11×11 grid:

```
. . . . . . . ★ . ★ .
★ . . . . ★ . . . . .
. . . . . . . ★ . ★ .
★ . ★ . . . . . . . .
. . . . ★ . ★ . . . .
. . ★ . . . . . ★ . .
. . . . ★ . . . . . ★
. ★ . . . . ★ . . . .
. . . ★ . . . . . . ★
. . . . . ★ . . ★ . .
. ★ . ★ . . . . . . .
```

`success` asserts at cycle 122. Continuing to clock, `O[7:0]` streams out:

> **(✱ TWO STARS ✱)**

## Detailed Writeup

For a full narrative of the reverse-engineering process — including wrong hypotheses, debugging war stories, and the moment I realised it was Star Battle — see [**PuzzleWriteup.md**](PuzzleWriteup.md).

---

## License

This repository contains my independent solution to the Jane Street ASIC Puzzle (2026). The puzzle files (`puzzle.gds`, `warmup.gds`, etc.) are property of Jane Street. All analysis scripts and writeup are my own work.
