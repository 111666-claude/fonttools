#!/usr/bin/env python3
"""Benchmark and equivalence check for CFF2 ``remove_unused_subroutines``.

The subroutine renumbering used to look up every ``callsubr``/``callgsubr``
operand in a sorted list with ``list.index()``, which is O(kept subrs) per
call.  This script builds a synthetic CFF2 font with many subroutines, times
the pruning path, and (optionally) checks that the result draws and compiles
identically before and after.

Usage
-----

Run against the current checkout::

    python3 Snippets/benchmark-remove-unused-subrs.py

Compare two checkouts, on the same machine in the same run::

    python3 Snippets/benchmark-remove-unused-subrs.py --repeat 7 \
        --baseline-lib /path/to/old/fonttools/Lib

Pass ``--verify`` to additionally compare glyph drawing and the compiled
binary table before/after pruning (and against the baseline result).
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from io import BytesIO


def build_font(num_subrs=6000, num_used=3000, num_glyphs=1):
    """Build a CFF2 font whose glyphs call a sparse subset of local subrs."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.cffLib import SubrsIndex
    from fontTools.misc.psCharStrings import T2CharString, calcSubrBias
    from fontTools.pens.t2CharStringPen import T2CharStringPen

    glyph_order = [".notdef"] + [f"g{i}" for i in range(num_glyphs - 1)]
    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap({})
    char_strings = {}
    for name in glyph_order:
        pen = T2CharStringPen(None, None, CFF2=True)
        pen.moveTo((0, 0))
        pen.lineTo((10, 0))
        pen.lineTo((0, 10))
        pen.closePath()
        char_strings[name] = pen.getCharString()
    fb.setupCFF2(char_strings)
    top = fb.font["CFF2"].cff[0]
    private = top.FDArray[0].Private
    global_subrs = fb.font["CFF2"].cff.GlobalSubrs

    subrs = SubrsIndex()
    old_bias = calcSubrBias(range(num_subrs))
    for i in range(num_subrs):
        subrs.append(
            T2CharString(
                # Zero deltas so the synthetic font's bounding box stays small
                # no matter how many subroutines are called.
                program=[0, 0, "rlineto", "return"],
                private=private,
                globalSubrs=global_subrs,
            )
        )
    private.Subrs = subrs

    # Spread the used indices over the addressable part of the index range:
    # Type 2 charstrings encode call operands as 16-bit ints, so old indices
    # beyond 65535 would otherwise trigger fontTools' legacy 4-byte-int
    # warning (indices are offset by the subroutine bias).
    usable = min(num_subrs, 65536)
    step = max(1, usable // num_used)
    used = list(range(0, usable, step))[:num_used]
    for name in glyph_order:
        char_string = char_strings[name]
        program = [0, 0, "rmoveto"]
        for old_index in used:
            program.extend([old_index - old_bias, "callsubr"])
        program.extend([0, 0, "rlineto", "endchar"])
        char_string.program = program
        char_string.private = private
        char_string.globalSubrs = global_subrs

    buf = BytesIO()
    fb.font.save(buf)
    buf.seek(0)
    return buf.getvalue()


def open_font(data):
    from fontTools.ttLib import TTFont

    return TTFont(BytesIO(data), recalcBBoxes=False)


def count_calls(font):
    """Number of callsubr/callgsubr tokens in the loaded glyph programs."""
    count = 0
    for name in font.getGlyphOrder():
        char_string = font["CFF2"].cff[0].CharStrings[name]
        char_string.decompile()
        count += char_string.program.count("callsubr")
        count += char_string.program.count("callgsubr")
    return count


def draw(font):
    from fontTools.pens.recordingPen import RecordingPen

    char_strings = font["CFF2"].cff[0].CharStrings
    out = []
    for name in font.getGlyphOrder():
        char_string = char_strings[name]
        pen = RecordingPen()
        char_string.draw(pen)
        out.append((char_string.width, pen.value))
    return out


def table_bytes(font):
    return font["CFF2"].compile(font)


def run_once(data, repeat):
    """Prune a fresh copy ``repeat`` times, returning the median seconds."""
    samples = []
    for _ in range(repeat):
        font = open_font(data)
        start = time.perf_counter()
        font["CFF2"].cff.remove_unused_subroutines()
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def verify(data):
    """Check drawing and compiled bytes are unchanged by pruning.

    Returns a dict of counters and the pruned CFF2 table bytes, so that two
    checkouts can also be compared against each other.
    """
    font = open_font(data)
    expected_draw = draw(font)
    calls = count_calls(font)
    font["CFF2"].cff.remove_unused_subroutines()
    pruned_draw = draw(font)

    reloaded = open_font(data)
    reloaded["CFF2"].cff.remove_unused_subroutines()
    reloaded_bytes = table_bytes(reloaded)
    pruned_bytes = table_bytes(font)
    assert expected_draw == pruned_draw, "drawing changed after pruning"
    assert reloaded_bytes == pruned_bytes, "compiled bytes differ after reopen"

    subrs = font["CFF2"].cff[0].FDArray[0].Private.Subrs
    return {
        "calls": calls,
        "kept": len(subrs),
        "draw_stable": expected_draw == pruned_draw,
        "binary_stable": reloaded_bytes == pruned_bytes,
        "pruned_bytes": pruned_bytes,
    }


def run_against(label, lib_path, args):
    if lib_path:
        sys.path.insert(0, lib_path)
    # Import lazily so that the extra sys.path entry wins.
    for name in list(sys.modules):
        if name == "fontTools" or name.startswith("fontTools."):
            del sys.modules[name]
    from fontTools.cffLib import __file__ as cfflib_file

    if lib_path:
        assert cfflib_file.startswith(lib_path), cfflib_file

    data = build_font(args.subrs, args.used, args.glyphs)
    print(f"{label}:")
    print(f"  fontTools: {cfflib_file}")
    result = {}
    if args.verify:
        result = verify(data)
        print(
            "  calls={calls} kept={kept} draw_stable={draw_stable} "
            "binary_stable={binary_stable}".format(**result)
        )
    elapsed = run_once(data, args.repeat)
    print(f"  median pruning time: {elapsed * 1000:.2f} ms ({args.repeat} runs)")

    if lib_path:
        sys.path.remove(lib_path)
    result["elapsed"] = elapsed
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subrs", type=int, default=6000)
    parser.add_argument("--used", type=int, default=3000)
    parser.add_argument("--glyphs", type=int, default=1)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument(
        "--verify",
        action="store_true",
        help="compare drawing and compiled CFF2 bytes before/after pruning",
    )
    parser.add_argument(
        "--baseline-lib",
        metavar="DIR",
        help="path to an older fontTools Lib directory to compare against",
    )
    args = parser.parse_args(argv)

    baseline = None
    if args.baseline_lib:
        baseline = run_against("baseline", args.baseline_lib, args)
    current = run_against("current", None, args)
    if baseline:
        print(f"speedup: {baseline['elapsed'] / current['elapsed']:.2f}x")
        if args.verify:
            same = baseline["pruned_bytes"] == current["pruned_bytes"]
            print(f"baseline/current compiled bytes identical: {same}")
            assert same, "baseline and current produce different CFF2 bytes"
    return 0


if __name__ == "__main__":
    sys.exit(main())
