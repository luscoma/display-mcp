"""Canvas geometry: the one leaf every other module in this package reads
its size from -- `WIDTH`/`HEIGHT`/`BEZEL_MARGIN`, plus `OFF_CANVAS_TOLERANCE`
(just as much a canvas constant as the size it's measured against;
`shapes.py`'s `_off_canvas()` is its only reader). Nothing here imports
from a sibling module -- it is the leaf the others build on.
"""

from __future__ import annotations

WIDTH, HEIGHT = 1200, 1600


BEZEL_MARGIN = 24


OFF_CANVAS_TOLERANCE = 64
