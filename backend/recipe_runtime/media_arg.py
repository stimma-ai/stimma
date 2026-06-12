"""Unified ``Media`` wrapper for recipe-sandbox callable inputs.

``code()``, ``create_image()``, and ``create_layout()`` each need a different
view of a media-typed input: the raw media id, a PIL image, or a bundle-
local filename. Exposing three different resolution rules invites the
agent to mix them up (e.g. calling ``fox_img.size`` on an int, or trying
to import ``stimma.library`` from the recipe sandbox to resolve an id).

One ``Media`` object replaces all three. Inside a callable:

  - ``m.id``       — library media id (``int``)
  - ``m.filename`` — string to interpolate into ``<img src=...>``; in
                     ``create_layout`` it's the bundle-relative name, in
                     ``code()`` and ``create_image()`` it's the library
                     file's basename.
  - ``m.path``     — absolute path to the library file on disk
  - ``m.pil``      — ``PIL.Image.Image`` opened lazily on first access
                     and cached. Blocking I/O — safe inside ``code()`` /
                     ``create_image`` / ``create_layout`` sync callables
                     (they run under ``asyncio.to_thread``).

``__str__`` returns ``filename`` so ``f"<img src='{m}'>"`` works. ``__int__``
returns ``id`` so legacy recipes that used a media-id int as a dict key
still work after the migration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


class Media:
    __slots__ = ("_id", "_path", "_filename", "_pil")

    def __init__(
        self,
        media_id: int,
        *,
        path: str,
        filename: Optional[str] = None,
    ) -> None:
        self._id = int(media_id)
        self._path = path
        self._filename = filename if filename is not None else Path(path).name
        self._pil: Any = None

    @property
    def id(self) -> int:
        return self._id

    @property
    def path(self) -> str:
        return self._path

    @property
    def filename(self) -> str:
        return self._filename

    @property
    def pil(self) -> Any:
        if self._pil is None:
            from utils.image_ops import open_oriented

            self._pil = open_oriented(self._path)
        return self._pil

    def __repr__(self) -> str:
        return f"Media(id={self._id}, filename={self._filename!r})"

    def __str__(self) -> str:
        return self._filename

    def __int__(self) -> int:
        return self._id

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Media):
            return self._id == other._id
        return NotImplemented

    def __hash__(self) -> int:
        return hash(("Media", self._id))
