from fontTools.misc.roundTools import noRound
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables as ot
from fontTools.ttLib.tables.otBase import OTTableWriter
from fontTools.varLib import HVAR_FIELDS, VVAR_FIELDS, _add_VHVAR
from fontTools.varLib import builder, models, varStore
from fontTools.varLib.errors import VarLibValidationError
from fontTools.misc.fixedTools import fixedToFloat as fi2fl
from fontTools.misc.cliTools import makeOutputFileName
from functools import partial
import logging

log = logging.getLogger("fontTools.varLib.avar")


def _get_advance_metrics(font, axisTags, tableFields):
    # There's two ways we can go from here:
    # 1. For each glyph, at each master peak, compute the value of the
    #    advance width at that peak.  Then pass these all to a VariationModel
    #    builder to compute back the deltas.
    # 2. For each master peak, pull out the deltas of the advance width directly,
    #    and feed these to the VarStoreBuilder, forgoing the remodeling step.
    # We'll go with the second option, as it's simpler, faster, and more direct.
    gvar = font["GVAR"] if "GVAR" in font else font["gvar"]
    vhAdvanceDeltasAndSupports = {}
    glyphOrder = font.getGlyphOrder()
    phantomIndex = tableFields.phantomIndex
    for glyphName in glyphOrder:
        supports = []
        deltas = []
        variations = gvar.variations.get(glyphName, [])

        for tv in variations:
            supports.append(tv.axes)
            phantoms = tv.coordinates[-4:]
            phantoms = phantoms[phantomIndex * 2 : phantomIndex * 2 + 2]
            assert len(phantoms) == 2
            phantoms[0] = phantoms[0][phantomIndex] if phantoms[0] is not None else 0
            phantoms[1] = phantoms[1][phantomIndex] if phantoms[1] is not None else 0
            deltas.append(phantoms[1] - phantoms[0])

        vhAdvanceDeltasAndSupports[glyphName] = (deltas, supports)

    vOrigDeltasAndSupports = None  # TODO

    return vhAdvanceDeltasAndSupports, vOrigDeltasAndSupports


def _get_advance_metrics_with_vOrig(font, axisTags, tableFields, vOrigSamples):
    vhAdvanceDeltasAndSupports, _ = _get_advance_metrics(font, axisTags, tableFields)
    vOrigDeltasAndSupports = _get_vOrig_metrics(font, axisTags, vOrigSamples)
    return vhAdvanceDeltasAndSupports, vOrigDeltasAndSupports


def _get_advance_metrics_without_gvar(font, axisTags, tableFields, vOrigSamples):
    # CFF2 variable fonts carry their outlines (and any phantom changes) in
    # the CFF2 blend operators, so they generally do not have a gvar table.
    # Vertical advances therefore cannot be derived here: hand out empty
    # advance deltas for every glyph and only build the VOrgMap from the
    # caller-supplied vertical-origin samples.
    glyphOrder = font.getGlyphOrder()
    vhAdvanceDeltasAndSupports = {glyphName: ([], []) for glyphName in glyphOrder}
    vOrigDeltasAndSupports = _get_vOrig_metrics(font, axisTags, vOrigSamples)
    return vhAdvanceDeltasAndSupports, vOrigDeltasAndSupports


def _normalize_vOrig_samples(font, axisTags, vOrigSamples):
    """Validate and normalize the caller-supplied vertical-origin samples.

    ``vOrigSamples`` is a sequence of ``(location, records)`` pairs. Each
    location is a dict of axis tag to normalized coordinate, the empty dict
    being the default location. ``records`` holds the explicit vertical
    origin of each measured glyph at that location; glyphs absent from a
    location (or mapped to ``None``) use the VORG default there.

    Returns a list of ``(location, records)`` pairs, each location normalized
    to contain only non-zero coordinates and restricted to the font's axes.
    """
    fvar = font["fvar"]
    validAxisTags = {axis.axisTag for axis in fvar.axes}
    glyphOrder = set(font.getGlyphOrder())

    samples = []
    seenLocations = set()
    for location, records in vOrigSamples:
        unknownAxes = set(location) - validAxisTags
        if unknownAxes:
            raise VarLibValidationError(
                "Vertical-origin sample location references unknown axis "
                f"tag(s): {sorted(unknownAxes)}"
            )
        normalizedLocation = {
            axisTag: coord for axisTag, coord in location.items() if coord != 0.0
        }
        locationKey = tuple(sorted(normalizedLocation.items()))
        if locationKey in seenLocations:
            raise VarLibValidationError(
                "Vertical-origin samples contain a duplicated location "
                f"{dict(locationKey)}"
            )
        seenLocations.add(locationKey)

        for glyphName, vOrig in records.items():
            if glyphName not in glyphOrder:
                raise VarLibValidationError(
                    "Vertical-origin sample references glyph not in the "
                    f"font: {glyphName!r}"
                )
            if vOrig is not None and not isinstance(vOrig, (int, float)):
                raise VarLibValidationError(
                    "Vertical-origin value for glyph "
                    f"{glyphName!r} must be a number or None, got "
                    f"{vOrig!r}"
                )
        samples.append((normalizedLocation, dict(records)))

    if not any(location for location, _ in samples):
        raise VarLibValidationError(
            "Vertical-origin samples must include at least one non-default "
            "location; the default location is derived from the VORG table"
        )
    return samples


def _get_vOrig_metrics(font, axisTags, vOrigSamples):
    """Build per-glyph vertical-origin deltas-and-supports from samples.

    The default (base) master values come from the font's own VORG table,
    keeping the distinction between its ``defaultVertOriginY`` fallback and
    its explicit VOriginRecords. Each non-default sample location becomes a
    master of a :class:`~fontTools.varLib.models.VariationModel`; glyphs that
    were not measured at a location contribute ``None`` and are handled by the
    model's sparse (sub-model) mechanism.
    """
    if "VORG" not in font:
        raise VarLibValidationError(
            "Cannot build vertical-origin variations without a VORG table"
        )
    vorg = font["VORG"]
    defaultVertOriginY = vorg.defaultVertOriginY
    glyphOrder = font.getGlyphOrder()

    samples = _normalize_vOrig_samples(font, axisTags, vOrigSamples)

    # The base master at the default location, seeded from VORG: an explicit
    # VOriginRecord wins, otherwise the VORG default applies.
    baseRecords = {}
    for glyphName in glyphOrder:
        baseRecords[glyphName] = (
            vorg.VOriginRecords[glyphName]
            if glyphName in vorg.VOriginRecords
            else defaultVertOriginY
        )

    locations = [{}]
    perLocationRecords = [baseRecords]
    for location, records in samples:
        if not location:
            # A sample at the default location must agree with VORG, which
            # already defines the base master.
            for glyphName, vOrig in records.items():
                effective = defaultVertOriginY if vOrig is None else vOrig
                if effective != baseRecords[glyphName]:
                    raise VarLibValidationError(
                        "Vertical-origin sample at the default location "
                        f"conflicts with the VORG table for glyph "
                        f"{glyphName!r}: {effective} != "
                        f"{baseRecords[glyphName]}"
                    )
            continue
        locations.append(location)
        perLocationRecords.append(records)

    model = models.VariationModel(locations, axisOrder=axisTags)

    vOrigDeltasAndSupports = {}
    for glyphName in glyphOrder:
        masterValues = [baseRecords[glyphName]]
        for records in perLocationRecords[1:]:
            if glyphName not in records or records[glyphName] is None:
                # Not measured at this non-default master: the glyph falls
                # back to the VORG default there.
                masterValues.append(None)
            else:
                masterValues.append(records[glyphName])
        vOrigDeltasAndSupports[glyphName] = model.getDeltasAndSupports(
            masterValues, round=round
        )

    return vOrigDeltasAndSupports


def add_HVAR(font):
    if "HVAR" in font:
        del font["HVAR"]
    axisTags = [axis.axisTag for axis in font["fvar"].axes]
    getAdvanceMetrics = partial(_get_advance_metrics, font, axisTags, HVAR_FIELDS)
    _add_VHVAR(font, axisTags, HVAR_FIELDS, getAdvanceMetrics)


def add_VVAR(font, vOrigSamples=None):
    """Add a ``VVAR`` table to a variable font.

    Vertical advances are, as before, derived from the gvar phantom points.
    When ``vOrigSamples`` is provided, a ``VOrgMap`` with vertical-origin
    variations is built in addition.

    ``vOrigSamples`` is a sequence of ``(location, records)`` pairs. Each
    location is a dict of axis tag to normalized coordinate (e.g.
    ``{"wght": 1.0}``), and ``records`` is a dict of glyph name to vertical
    origin measured at that location; a missing glyph or a ``None`` value
    means the glyph uses the VORG default at that location. The values at
    the default location (empty location dict) are taken from the font's
    own ``VORG`` table, distinguishing its ``defaultVertOriginY`` from
    explicit records; samples must include at least one non-default
    location. When ``vOrigSamples`` is ``None`` (the default) the previous
    behavior is preserved and no ``VOrgMap`` is built.
    """
    if "VVAR" in font:
        del font["VVAR"]
    axisTags = [axis.axisTag for axis in font["fvar"].axes]
    if vOrigSamples is None:
        getAdvanceMetrics = partial(_get_advance_metrics, font, axisTags, VVAR_FIELDS)
    elif "gvar" not in font and "GVAR" not in font:
        # CFF2 variable fonts have no gvar; only the sampled VOrgMap can be
        # built, vertical advances are left without variations.
        getAdvanceMetrics = partial(
            _get_advance_metrics_without_gvar,
            font,
            axisTags,
            VVAR_FIELDS,
            vOrigSamples,
        )
    else:
        getAdvanceMetrics = partial(
            _get_advance_metrics_with_vOrig,
            font,
            axisTags,
            VVAR_FIELDS,
            vOrigSamples,
        )
    _add_VHVAR(font, axisTags, VVAR_FIELDS, getAdvanceMetrics)


def main(args=None):
    """Add `HVAR` table to variable font."""

    if args is None:
        import sys

        args = sys.argv[1:]

    from fontTools import configLogger
    from fontTools.designspaceLib import DesignSpaceDocument
    import argparse

    parser = argparse.ArgumentParser(
        "fonttools varLib.hvar",
        description="Add `HVAR` table from to variable font.",
    )
    parser.add_argument("font", metavar="varfont.ttf", help="Variable-font file.")
    parser.add_argument(
        "-o",
        "--output-file",
        type=str,
        help="Output font file name.",
    )

    options = parser.parse_args(args)

    configLogger(level="WARNING")

    font = TTFont(options.font)
    if not "fvar" in font:
        log.error("Not a variable font.")
        return 1

    add_HVAR(font)
    if "vmtx" in font or "VMTX" in font:
        add_VVAR(font)

    if options.output_file is None:
        outfile = makeOutputFileName(options.font, overWrite=True, suffix=".hvar")
    else:
        outfile = options.output_file
    if outfile:
        log.info("Saving %s", outfile)
        font.save(outfile)


if __name__ == "__main__":
    import sys

    sys.exit(main())
