import sys
from fontTools.ttLib import OPTIMIZE_FONT_SPEED, TTLibError, TTLibFileIsCollectionError
from fontTools.ttLib.ttFont import *
from fontTools.ttLib.ttCollection import TTCollection


def main(args=None):
    """Open/save fonts with TTFont() or TTCollection()

      ./fonttools ttLib [-oFILE] [-yNUMBER] files...

    If multiple files are given on the command-line,
    they are each opened (as a font or collection),
    and added to the font list.

    If -o (output-file) argument is given, the font
    list is then saved to the output file, either as
    a single font, if there is only one font, or as
    a collection otherwise.

    If -y (font-number) argument is given, only the
    specified font from collections is opened.

    The above allow extracting a single font from a
    collection, or combining multiple fonts into a
    collection.

    If --lazy or --no-lazy are give, those are passed
    to the TTFont() or TTCollection() constructors.
    """
    from fontTools import configLogger

    if args is None:
        args = sys.argv[1:]

    import argparse

    parser = argparse.ArgumentParser(
        "fonttools ttLib",
        description="Open/save fonts with TTFont() or TTCollection()",
        epilog="""
		If multiple files are given on the command-line,
		they are each opened (as a font or collection),
		and added to the font list.

		The above, when combined with -o / --output,
		allows for extracting a single font from a
		collection, or combining multiple fonts into a
		collection.
		""",
    )
    parser.add_argument("font", metavar="font", nargs="*", help="Font file.")
    parser.add_argument(
        "-t", "--table", metavar="table", action="append", help="Tables to decompile."
    )
    parser.add_argument(
        "-o", "--output", metavar="FILE", default=None, help="Output file."
    )
    parser.add_argument(
        "-y", metavar="NUMBER", default=-1, help="Font number to load from collections."
    )
    parser.add_argument(
        "--lazy", action="store_true", default=None, help="Load fonts lazily."
    )
    parser.add_argument(
        "--no-lazy", dest="lazy", action="store_false", help="Load fonts immediately."
    )
    parser.add_argument(
        "--flavor",
        dest="flavor",
        default=None,
        help="Flavor of output font. 'woff' or 'woff2'.",
    )
    parser.add_argument(
        "--no-recalc-timestamp",
        dest="recalcTimestamp",
        action="store_false",
        help="Keep the original font 'modified' timestamp.",
    )
    parser.add_argument(
        "-b",
        dest="recalcBBoxes",
        action="store_false",
        help="Don't recalc glyph bounding boxes: use the values in the original font.",
    )
    parser.add_argument(
        "--optimize-font-speed",
        action="store_true",
        help=(
            "Enable optimizations that prioritize speed over file size. This "
            "mainly affects how glyf table and gvar / VARC tables are compiled."
        ),
    )
    options = parser.parse_args(args)

    fontNumber = int(options.y) if options.y is not None else None
    outFile = options.output
    lazy = options.lazy
    flavor = options.flavor
    tables = options.table
    recalcBBoxes = options.recalcBBoxes
    recalcTimestamp = options.recalcTimestamp
    optimizeFontSpeed = options.optimize_font_speed

    fonts = []
    # Track the collections we open so we can close them (and thus every
    # member font's reader) if an error occurs before the fonts are handed
    # off to a freshly built TTCollection, which takes ownership of them.
    collections = []
    try:
        for f in options.font:
            try:
                font = TTFont(
                    f,
                    recalcBBoxes=recalcBBoxes,
                    recalcTimestamp=recalcTimestamp,
                    fontNumber=fontNumber,
                    lazy=lazy,
                )
                fonts.append(font)
            except TTLibFileIsCollectionError:
                try:
                    collection = TTCollection(f, lazy=lazy)
                except Exception as e:
                    raise TTLibError(f"Failed to open collection {f!r}: {e}") from e
                collections.append(collection)
                fonts.extend(collection.fonts)

        if tables is None:
            if lazy is False:
                tables = ["*"]
            else:
                tables = []
        for fontIndex, font in enumerate(fonts):
            # The speed-first config is per font, so apply it to every
            # member of a collection as well as to standalone fonts.
            if optimizeFontSpeed:
                font.cfg[OPTIMIZE_FONT_SPEED] = True
            if "GlyphOrder" in tables:
                font.getGlyphOrder()
            # When --optimize-font-speed is in effect and no -t tables were
            # given, decompile only the tables whose compilation the option
            # changes; resolve the set per font since collection members can
            # have different tables.
            if optimizeFontSpeed and options.table is None and "*" not in tables:
                fontTables = {"glyf", "gvar", "VARC"}.intersection(font.keys())
            elif "*" in tables:
                fontTables = font.keys()
            else:
                fontTables = tables
            for table in fontTables:
                try:
                    font[table]  # Decompiles
                except Exception as e:
                    readerFile = font.reader.file if font.reader is not None else None
                    fontName = getattr(readerFile, "name", f"<font #{fontIndex}>")
                    raise TTLibError(
                        f"Failed to process table {table!r} of font #{fontIndex} "
                        f"in {fontName!r}: {e}"
                    ) from e

        if outFile is not None:
            if len(fonts) == 1:
                try:
                    fonts[0].flavor = flavor
                    fonts[0].save(outFile)
                except Exception as e:
                    raise TTLibError(
                        f"Failed to save font #0 to {outFile!r}: {e}"
                    ) from e
            else:
                if flavor is not None:
                    raise TTLibError("Cannot set flavor for collections.")
                collection = TTCollection()
                collection.fonts = fonts
                try:
                    collection.save(outFile)
                except Exception as e:
                    raise TTLibError(
                        f"Failed to save collection to {outFile!r}: {e}"
                    ) from e
    finally:
        # Close every input resource we opened ourselves, on both success and
        # failure. In particular a lazy TTCollection keeps the input file open
        # until its member fonts are closed; without this it would only be
        # reclaimed (with a ResourceWarning) at garbage collection time.
        for collection in collections:
            collection.close()
        for font in fonts:
            font.close()


if __name__ == "__main__":
    sys.exit(main())
