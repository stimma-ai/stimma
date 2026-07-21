"""Timeline documents: op-log working store, pure op core, snapshot serializer.

The canonical `.stimmatimeline.json` snapshot schema and the op vocabulary are
governed by plans-level review; keep both small and change them deliberately.
"""

from .ops import TimelineOpError, apply_op, compute_inverse, new_entry_id  # noqa: F401
from .store import TimelineProject, TimelineStoreError, get_project  # noqa: F401
from .serializer import serialize_snapshot  # noqa: F401
