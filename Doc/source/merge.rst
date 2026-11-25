####################################
merge: Merge multiple fonts into one
####################################

.. rubric:: Overview:
   :heading-level: 2

:mod:`fontTools.merge` provides both a library and a command line interface
(``fonttools merge``) for merging multiple fonts together.

If the merged BMP mapping exceeds the 16-bit size limits of a ``cmap`` format 4
subtable, the merger writes the BMP mapping with a format 12 subtable instead.
All nominal mappings and Unicode variation sequences are retained; such fonts
require a reader that supports format 12. BMP mappings that fit in format 4 keep
their format 4 representation.

.. autoclass:: fontTools.merge.Merger
   :members:
   :undoc-members:
