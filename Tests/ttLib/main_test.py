import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import (
    TTCollection,
    TTFont,
    TTLibError,
    __main__,
)

TEST_DATA = Path(__file__).parent / "data"
TTC_DATA = Path(__file__).parent.parent / "ttx" / "data" / "TestTTC.ttc"


@pytest.fixture
def ttfont_path():
    font = TTFont()
    font.importXML(TEST_DATA / "TestTTF-Regular.ttx")
    with tempfile.NamedTemporaryFile(suffix=".ttf", delete=False) as fp:
        font_path = Path(fp.name)
        font.save(font_path)
    yield font_path
    font_path.unlink()


@pytest.fixture
def ttcollection_path():
    font1 = TTFont()
    font1.importXML(TEST_DATA / "TestTTF-Regular.ttx")
    font2 = TTFont()
    font2.importXML(TEST_DATA / "TestTTF-Regular.ttx")
    coll = TTCollection()
    coll.fonts = [font1, font2]
    with tempfile.NamedTemporaryFile(suffix=".ttf", delete=False) as fp:
        collection_path = Path(fp.name)
        coll.save(collection_path)
    yield collection_path
    collection_path.unlink()


@pytest.fixture(params=[None, "woff"])
def flavor(request):
    return request.param


def test_ttLib_main_as_subprocess(ttfont_path):
    subprocess.run(
        [sys.executable, "-m", "fontTools.ttLib", str(ttfont_path)], check=True
    )


def test_ttLib_open_ttfont(ttfont_path):
    __main__.main([str(ttfont_path)])


def test_ttLib_open_save_ttfont(tmp_path, ttfont_path, flavor):
    output_path = tmp_path / "TestTTF-Regular.ttf"
    args = ["-o", str(output_path), str(ttfont_path)]
    if flavor is not None:
        args.extend(["--flavor", flavor])

    __main__.main(args)

    assert output_path.exists()
    assert TTFont(output_path).getGlyphOrder() == TTFont(ttfont_path).getGlyphOrder()


def test_ttLib_open_ttcollection(ttcollection_path):
    __main__.main(["-y", "0", str(ttcollection_path)])


def test_ttLib_open_ttcollection_save_single_font(tmp_path, ttcollection_path, flavor):
    for i in range(2):
        output_path = tmp_path / f"TestTTF-Regular#{i}.ttf"
        args = ["-y", str(i), "-o", str(output_path), str(ttcollection_path)]
        if flavor is not None:
            args.extend(["--flavor", flavor])

        __main__.main(args)

        assert output_path.exists()
        assert (
            TTFont(output_path).getGlyphOrder()
            == TTCollection(ttcollection_path)[i].getGlyphOrder()
        )


def test_ttLib_open_ttcollection_save_ttcollection(tmp_path, ttcollection_path):
    output_path = tmp_path / "TestTTF.ttc"

    __main__.main(["-o", str(output_path), str(ttcollection_path)])

    assert output_path.exists()
    assert len(TTCollection(output_path)) == len(TTCollection(ttcollection_path))


def test_ttLib_open_multiple_fonts_save_ttcollection(tmp_path, ttfont_path):
    output_path = tmp_path / "TestTTF.ttc"

    __main__.main(["-o", str(output_path), str(ttfont_path), str(ttfont_path)])

    assert output_path.exists()

    coll = TTCollection(output_path)
    assert len(coll) == 2
    assert coll[0].getGlyphOrder() == coll[1].getGlyphOrder()


# ---------------------------------------------------------------------------
# --optimize-font-speed
# ---------------------------------------------------------------------------


@pytest.fixture
def distinct_ttcollection_path():
    """A two-member TTC whose members carry different glyph orders, so that
    any per-member mix-up would show up in the outline comparison."""
    font1 = TTFont()
    font1.importXML(TEST_DATA / "TestTTF-Regular.ttx")
    font2 = TTFont()
    font2.importXML(TEST_DATA / "TestTTF-Regular.ttx")
    # Reverse the glyph order (and glyf contents) of the second member.
    glyph_order = font2.getGlyphOrder()
    font2.setGlyphOrder(list(reversed(glyph_order)))
    font2["glyf"].glyphs = {
        name: font2["glyf"].glyphs[name] for name in reversed(glyph_order)
    }
    coll = TTCollection()
    coll.fonts = [font1, font2]
    with tempfile.NamedTemporaryFile(suffix=".ttc", delete=False) as fp:
        collection_path = Path(fp.name)
        coll.save(collection_path)
    yield collection_path
    collection_path.unlink()


def _raw_table(font_path, member, tag):
    """Read a table's compiled bytes straight from the saved file."""
    font = TTFont(font_path, fontNumber=member)
    try:
        return font.reader[tag]
    finally:
        font.close()


def _outlines_and_metrics(font_path, member):
    font = TTFont(font_path, fontNumber=member)
    try:
        glyph_set = font.getGlyphSet()
        outlines = {}
        for glyph_name in font.getGlyphOrder():
            pen = RecordingPen()
            glyph_set[glyph_name].draw(pen)
            outlines[glyph_name] = pen.value
        metrics = dict(font["hmtx"].metrics)
        return outlines, metrics
    finally:
        font.close()


@pytest.mark.parametrize("lazy", [None, True, False])
def test_optimize_font_speed_single_font(tmp_path, ttfont_path, lazy):
    speed_path = tmp_path / "speed.ttf"
    size_path = tmp_path / "size.ttf"

    speed_args = ["--optimize-font-speed", "-o", str(speed_path), str(ttfont_path)]
    size_args = ["-o", str(size_path), str(ttfont_path)]
    if lazy is True:
        for args in (speed_args, size_args):
            args.insert(0, "--lazy")
    elif lazy is False:
        for args in (speed_args, size_args):
            args.insert(0, "--no-lazy")

    __main__.main(speed_args)
    __main__.main(size_args)

    # Evidence that the speed option actually changed compilation: the glyf
    # table compiled for speed is larger than the size-optimized one.
    speed_glyf = _raw_table(speed_path, 0, "glyf")
    size_glyf = _raw_table(size_path, 0, "glyf")
    assert speed_glyf != size_glyf
    assert len(speed_glyf) > len(size_glyf)

    # ... while outlines and metrics survive the save/reopen round-trip.
    speed_outlines, speed_metrics = _outlines_and_metrics(speed_path, 0)
    size_outlines, size_metrics = _outlines_and_metrics(size_path, 0)
    assert speed_outlines == size_outlines
    assert speed_metrics == size_metrics


@pytest.mark.parametrize("lazy", [None, True, False])
def test_optimize_font_speed_applies_to_every_ttc_member(
    tmp_path, distinct_ttcollection_path, lazy
):
    speed_path = tmp_path / "speed.ttc"
    size_path = tmp_path / "size.ttc"

    speed_args = [
        "--optimize-font-speed",
        "-o",
        str(speed_path),
        str(distinct_ttcollection_path),
    ]
    size_args = ["-o", str(size_path), str(distinct_ttcollection_path)]
    if lazy is True:
        speed_args.insert(0, "--lazy")
        size_args.insert(0, "--lazy")
    elif lazy is False:
        speed_args.insert(0, "--no-lazy")
        size_args.insert(0, "--no-lazy")

    # Previously this raised UnboundLocalError because the per-font branch
    # that referenced 'font' was skipped entirely for collections.
    __main__.main(speed_args)
    __main__.main(size_args)

    speed_coll = TTCollection(speed_path)
    size_coll = TTCollection(size_path)
    assert len(speed_coll) == len(size_coll) == 2
    # member order must be preserved
    assert speed_coll[0].getGlyphOrder() == size_coll[0].getGlyphOrder()
    assert speed_coll[1].getGlyphOrder() == size_coll[1].getGlyphOrder()
    speed_coll.close()
    size_coll.close()

    for member in range(2):
        # Per-member evidence that speed-first compilation really happened.
        speed_glyf = _raw_table(speed_path, member, "glyf")
        size_glyf = _raw_table(size_path, member, "glyf")
        assert speed_glyf != size_glyf
        assert len(speed_glyf) > len(size_glyf)

        # Outlines and metrics must match member by member after reopen.
        speed_outlines, speed_metrics = _outlines_and_metrics(speed_path, member)
        size_outlines, size_metrics = _outlines_and_metrics(size_path, member)
        assert speed_outlines == size_outlines
        assert speed_metrics == size_metrics


def test_optimize_font_speed_without_optimizable_tables(tmp_path):
    # CFF2-based OTF has neither glyf, gvar nor VARC: nothing to optimize,
    # but the command must still succeed and round-trip the font.
    otf_path = TEST_DATA / "I.otf"
    output_path = tmp_path / "I.otf"

    __main__.main(["--optimize-font-speed", "-o", str(output_path), str(otf_path)])

    assert output_path.exists()
    before = TTFont(otf_path)
    after = TTFont(output_path)
    assert after.getGlyphOrder() == before.getGlyphOrder()
    assert dict(after["hmtx"].metrics) == dict(before["hmtx"].metrics)
    before.close()
    after.close()


def test_optimize_font_speed_mixed_collection_inputs(tmp_path, ttfont_path):
    # A standalone font plus a collection on one command line must end up as
    # a collection in which every member is speed-optimized.
    speed_path = tmp_path / "mixed-speed.ttc"
    size_path = tmp_path / "mixed-size.ttc"

    __main__.main(
        [
            "--optimize-font-speed",
            "-o",
            str(speed_path),
            str(ttfont_path),
            str(TTC_DATA),
        ]
    )
    __main__.main(["-o", str(size_path), str(ttfont_path), str(TTC_DATA)])

    speed_coll = TTCollection(speed_path)
    size_coll = TTCollection(size_path)
    try:
        assert len(speed_coll) == len(size_coll) == 3
        for member in range(3):
            # Every member, including those that came in through the TTC, must
            # show the speed-compilation signature in its glyf bytes.
            assert _raw_table(speed_path, member, "glyf") != _raw_table(
                size_path, member, "glyf"
            )
    finally:
        speed_coll.close()
        size_coll.close()


def test_optimize_font_speed_corrupt_member_raises_locatable_error(
    tmp_path, distinct_ttcollection_path
):
    # Keep the TTC header intact but overwrite the middle of member 0's glyf
    # table with junk. glyf glyphs are expanded lazily, so the failure
    # surfaces when the collection is saved again.
    font = TTFont(str(distinct_ttcollection_path), fontNumber=0)
    glyf_offset = font.reader.tables["glyf"].offset
    glyf_length = font.reader.tables["glyf"].length
    font.close()

    corrupt_path = tmp_path / "corrupt.ttc"
    data = bytearray(distinct_ttcollection_path.read_bytes())
    start = glyf_offset + glyf_length // 2
    data[start : start + 8] = b"\xff" * 8
    corrupt_path.write_bytes(data)
    output_path = tmp_path / "out.ttc"

    with pytest.raises(TTLibError) as exc_info:
        __main__.main(
            ["--optimize-font-speed", "-o", str(output_path), str(corrupt_path)]
        )

    message = str(exc_info.value)
    # The wrapped error must name the collection output and identify the
    # failing member through the TTCollection.save() context.
    assert "Failed to save collection" in message
    assert str(output_path) in message
    assert "font #0" in message
    assert isinstance(exc_info.value.__cause__, TTLibError)
    # Nothing usable should have been left behind on failure.
    assert not output_path.exists()


def test_optimize_font_speed_unreadable_collection_raises_locatable_error(tmp_path):
    import struct

    bad_path = tmp_path / "bad.ttc"
    # A structurally valid TTC header claiming two fonts whose offset table
    # points nowhere: opening the first member must fail, and the CLI must
    # turn that into a locatable TTLibError naming the collection.
    header = b"ttcf" + struct.pack(">II", 0x00010000, 2) + struct.pack(">II", 0, 0)
    bad_path.write_bytes(header)

    with pytest.raises(TTLibError) as exc_info:
        __main__.main(["--optimize-font-speed", str(bad_path)])

    message = str(exc_info.value)
    assert str(bad_path) in message
    assert "Failed to open collection" in message


@pytest.mark.parametrize("lazy", [None, True, False])
def test_optimize_font_speed_closes_owned_resources(
    tmp_path, distinct_ttcollection_path, lazy
):
    import gc
    import warnings

    output_path = tmp_path / "out.ttc"
    args = [
        "--optimize-font-speed",
        "-o",
        str(output_path),
        str(distinct_ttcollection_path),
    ]
    if lazy is True:
        args.insert(0, "--lazy")
    elif lazy is False:
        args.insert(0, "--no-lazy")

    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceWarning)
        __main__.main(args)
        gc.collect()

    assert output_path.exists()


def test_failed_ttfont_constructor_does_not_leak_file():
    import gc
    import warnings

    # Opening a collection through the single-font TTFont() entry point used to
    # leave the freshly opened file behind when SFNTReader raised.
    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceWarning)
        with pytest.raises(TTLibError):
            TTFont(str(TTC_DATA), lazy=True)
        gc.collect()


def test_optimize_font_speed_preserves_ttc_table_sharing(tmp_path):
    # When input members share identical tables, saving keeps them shared
    # (the collection is rewritten via TTCollection.save(shareTables=True)).
    output_speed = tmp_path / "speed.ttc"
    output_size = tmp_path / "size.ttc"

    __main__.main(["--optimize-font-speed", "-o", str(output_speed), str(TTC_DATA)])
    __main__.main(["-o", str(output_size), str(TTC_DATA)])

    # Both members of TestTTC.ttc are identical: offsets of shared tables must
    # coincide between the two member fonts in both outputs.
    def shared_offsets(path):
        per_member = []
        for member in range(2):
            font = TTFont(path, fontNumber=member)
            per_member.append(
                {tag: entry.offset for tag, entry in font.reader.tables.items()}
            )
            font.close()
        return per_member

    for path in (output_speed, output_size):
        offsets = shared_offsets(path)
        common = set(offsets[0]) & set(offsets[1])
        assert common  # sanity check
        assert all(offsets[0][tag] == offsets[1][tag] for tag in common)

    # And the speed output really differs at the glyf level.
    assert _raw_table(output_speed, 0, "glyf") != _raw_table(output_size, 0, "glyf")
