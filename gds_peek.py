#!/usr/bin/env python3
"""
gds_peek.py - dump every human-readable thing in a GDSII file.

Usage:
    python3 gds_peek.py puzzle.gds

Pure standard library. No pip installs, no EDA tools.
"""

import struct
import sys
from collections import Counter

# GDSII record types. The record type is byte 2 of each 4-byte record header.
REC = {
    0x00: 'HEADER',   0x01: 'BGNLIB',   0x02: 'LIBNAME',  0x03: 'UNITS',
    0x04: 'ENDLIB',   0x05: 'BGNSTR',   0x06: 'STRNAME',  0x07: 'ENDSTR',
    0x08: 'BOUNDARY', 0x09: 'PATH',     0x0A: 'SREF',     0x0B: 'AREF',
    0x0C: 'TEXT',     0x0D: 'LAYER',    0x0E: 'DATATYPE', 0x0F: 'WIDTH',
    0x10: 'XY',       0x11: 'ENDEL',    0x12: 'SNAME',    0x13: 'COLROW',
    0x16: 'TEXTTYPE', 0x17: 'PRESENTATION', 0x19: 'STRING',
    0x1A: 'STRANS',   0x1B: 'MAG',      0x1C: 'ANGLE',
    0x2D: 'BOX',      0x2E: 'BOXTYPE',
}

ELEMENTS = ('BOUNDARY', 'PATH', 'TEXT', 'SREF', 'AREF', 'BOX')


def gds_real(b):
    """Decode an 8-byte GDSII real. NOT IEEE 754 - it is excess-64, base-16."""
    sign = -1.0 if b[0] & 0x80 else 1.0
    exponent = (b[0] & 0x7F) - 64
    mantissa = int.from_bytes(b[1:8], 'big') / float(1 << 56)
    return sign * mantissa * (16.0 ** exponent)


def records(path):
    """Yield (record_type, data_type, payload) for every record in the file."""
    with open(path, 'rb') as f:
        while True:
            header = f.read(4)
            if len(header) < 4:
                return
            length = struct.unpack('>H', header[:2])[0]
            if length < 4:
                return
            yield header[2], header[3], f.read(length - 4)


def as_text(data):
    return data.rstrip(b'\x00').decode('ascii', 'replace')


def as_int16(data):
    return struct.unpack('>h', data[:2])[0] if len(data) >= 2 else None


def main(path):
    libname = None
    units = None
    version = None
    defined_cells = []          # STRNAME: cells DEFINED in this file
    referenced_cells = Counter()  # SNAME: cells INSTANTIATED, with counts
    labels = []                 # (layer, texttype, string) from TEXT elements
    shapes_by_layer = Counter()  # (layer, datatype) -> polygon count
    element_counts = Counter()

    current_element = None
    current_layer = None
    current_dtype = None

    for rtype, dtype, data in records(path):
        name = REC.get(rtype)

        if name == 'HEADER':
            version = as_int16(data)
        elif name == 'LIBNAME':
            libname = as_text(data)
        elif name == 'UNITS' and len(data) >= 16:
            units = (gds_real(data[0:8]), gds_real(data[8:16]))
        elif name == 'STRNAME':
            defined_cells.append(as_text(data))
        elif name == 'SNAME':
            referenced_cells[as_text(data)] += 1
        elif name in ELEMENTS:
            element_counts[name] += 1
            current_element = name
            current_layer = current_dtype = None
        elif name == 'LAYER':
            current_layer = as_int16(data)
        elif name in ('DATATYPE', 'TEXTTYPE', 'BOXTYPE'):
            current_dtype = as_int16(data)
        elif name == 'STRING':
            labels.append((current_layer, current_dtype, as_text(data)))
        elif name == 'ENDEL':
            if current_element in ('BOUNDARY', 'PATH', 'BOX') and current_layer is not None:
                shapes_by_layer[(current_layer, current_dtype)] += 1
            current_element = None

    # ---------------------------------------------------------------- report

    print('=' * 68)
    print('FILE'.ljust(24), path)
    print('GDSII version'.ljust(24), version)
    print('Library name'.ljust(24), repr(libname))
    if units:
        print('User unit / DB unit'.ljust(24), units[0])
        print('Metres per DB unit'.ljust(24), f'{units[1]:g}   '
              f'(1 DB unit = {units[1] * 1e9:g} nm)')
    print()

    print('ELEMENT COUNTS')
    for k, v in element_counts.most_common():
        print(f'  {k:<12} {v:>10,}')
    print()

    print(f'LAYERS  ({len(shapes_by_layer)} distinct layer/datatype pairs)')
    print(f'  {"layer":>6} {"dtype":>6} {"shapes":>12}')
    for (layer, dtype), n in sorted(shapes_by_layer.items()):
        print(f'  {layer:>6} {dtype:>6} {n:>12,}')
    print()

    uniq_defined = sorted(set(defined_cells))
    print(f'CELL DEFINITIONS (STRNAME): {len(uniq_defined)} distinct')
    for n in uniq_defined[:80]:
        print('   ', n)
    if len(uniq_defined) > 80:
        print(f'    ... and {len(uniq_defined) - 80} more')
    print()

    print(f'CELL INSTANTIATIONS (SNAME): {len(referenced_cells)} distinct, '
          f'{sum(referenced_cells.values()):,} total placements')
    for n, c in referenced_cells.most_common(80):
        print(f'  {c:>8,}  {n}')
    if len(referenced_cells) > 80:
        print(f'    ... and {len(referenced_cells) - 80} more')
    print()

    top = sorted(set(defined_cells) - set(referenced_cells))
    print('TOP CELL(S)  [defined but never instantiated]:', top if top else '(none found)')
    print()

    print(f'TEXT LABELS: {len(labels)} total')
    by_layer = {}
    for layer, dtype, s in labels:
        by_layer.setdefault((layer, dtype), []).append(s)
    for key in sorted(by_layer, key=lambda k: (k[0] is None, k)):
        strings = by_layer[key]
        print(f'  layer {key[0]}/{key[1]}  ->  {len(strings)} labels')
        for s in sorted(set(strings))[:60]:
            print('       ', s)
        if len(set(strings)) > 60:
            print(f'        ... and {len(set(strings)) - 60} more distinct')
    print('=' * 68)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
