##############
interpolatable
##############

Note also that :mod:`varLib.interpolatable` supports some :doc:`optional </optional>`
external libraries.

When location data is available, master pairs are chosen using a
minimum spanning tree within each discrete-axis subspace. An edge is allowed
only when one master's set of nonzero continuous axes is a subset of the
other's (including equal sets). Edges that change fewer coordinate values
take priority, with squared Euclidean distance breaking ties. Thus matching
coordinates favor comparisons along grid lines, while one-axis masters are
still compared to their nearest neighbors. Each discrete-axis subspace is
rooted at a default master at zero on all continuous axes; a disconnected
subspace without such a default is rooted deterministically at its
lowest-index master. Without location data, masters are compared along a
chain in input order.

.. automodule:: fontTools.varLib.interpolatable
   :members:
   :undoc-members:
