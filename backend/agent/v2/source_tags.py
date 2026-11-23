"""Which library media a piece of image data came from, carried on the data itself.

Agent code makes files in ways the platform never sees: open a tool result, crop
it, save it under a new name. To know what such a file was made from, each image
the code opens is tagged with where it came from, the tag travels with the
pixels through Pillow and NumPy, and saving the image records the tag for the
written file (``file_sources``). Order of work does not matter: ten results
loaded up front and saved one by one each keep their own source.

A tag is an ordered tuple of keys: a library media id, or the content hash of a
file (resolved to library media, or to that file's own recorded sources, when
the output is saved). An operation over several images carries all their keys.

Tags follow pixels, not decisions: an image opened only to measure it is not a
source, and neither is one that only steered an ``if``. Data that leaves Pillow
and NumPy (raw bytes, an external encoder) loses its tag; such code declares its
sources with ``stimma.record_sources`` or ``sources=`` on save.

Tagging is on only while agent code runs (``tracking``). Outside it every patch
here is a pass-through.
"""
from __future__ import annotations

import contextlib
import contextvars
import functools
import os
import types
from pathlib import Path
from typing import Any, Iterable

import numpy
from PIL import Image, ImageChops

from core.logging import get_logger

log = get_logger(__name__)

_ATTR = "_stimma_sources"
Key = int | str

class Tracking:
    """One run of agent code: the chat workspace whose ledger records what its
    saved files were made from, and whether it opened any image file."""

    def __init__(self, workspace_dir: Path | str):
        self.workspace_dir = Path(workspace_dir)
        self.opened = False


_current: contextvars.ContextVar[Tracking | None] = contextvars.ContextVar("stimma_source_tracking", default=None)


@contextlib.contextmanager
def tracking(workspace_dir: Path | str):
    """Tag images opened, and record images saved, by code run inside."""
    state = Tracking(workspace_dir)
    token = _current.set(state)
    try:
        yield state
    finally:
        _current.reset(token)


@contextlib.contextmanager
def untracked():
    """The platform's own work on behalf of agent code (an SDK call saving a
    file, reading its size) is not the code opening or making an image."""
    token = _current.set(None)
    try:
        yield
    finally:
        _current.reset(token)


def sources_of(value: Any) -> tuple[Key, ...]:
    """The tag on an image or array; empty for anything else."""
    if isinstance(value, (Image.Image, numpy.ndarray)):
        return getattr(value, _ATTR, None) or ()
    return ()


def _collect(values: Iterable[Any], depth: int = 2) -> tuple[Key, ...]:
    keys: dict[Key, None] = {}
    for value in values:
        if isinstance(value, (list, tuple)) and depth:
            keys.update(dict.fromkeys(_collect(value, depth - 1)))
        else:
            keys.update(dict.fromkeys(sources_of(value)))
    return tuple(keys)


def tag(value: Any, keys: Iterable[Key]) -> Any:
    """Set the tag on an image or array (a no-op for an empty tag)."""
    keys = tuple(dict.fromkeys(keys))
    if keys and isinstance(value, (Image.Image, SourcedArray)):
        setattr(value, _ATTR, keys)
    return value


# --- NumPy --------------------------------------------------------------------

# A blank array shaped like an image holds none of its pixels.
_SHAPE_ONLY = {"zeros_like", "ones_like", "empty_like", "full_like"}


class SourcedArray(numpy.ndarray):
    """An array that remembers the images its values came from."""

    def __array_finalize__(self, obj):
        setattr(self, _ATTR, getattr(obj, _ATTR, None) or ())

    def __array_ufunc__(self, ufunc, method, *inputs, out=None, **kwargs):
        keys = _collect((*inputs, *(out or ()), *kwargs.values()))
        inputs = tuple(_plain(i) for i in inputs)
        kwargs = {name: _plain(value) for name, value in kwargs.items()}  # where=mask
        if out is not None:
            kwargs["out"] = tuple(_plain(o) for o in out)
        result = getattr(ufunc, method)(*inputs, **kwargs)
        if out is not None:
            # In place (a += b): hand back the caller's own arrays, retagged.
            for o in out:
                tag(o, keys)
            return out[0] if len(out) == 1 else out
        return _retag(result, keys)

    def __array_function__(self, func, types, args, kwargs):
        result = super().__array_function__(func, types, args, kwargs)
        if getattr(func, "__name__", "") in _SHAPE_ONLY:
            return result.view(numpy.ndarray) if isinstance(result, numpy.ndarray) else result
        return _retag(result, _collect((*args, *kwargs.values())))

    def __setitem__(self, index, value):
        super().__setitem__(index, value)
        extra = sources_of(value)
        target = self
        while extra and isinstance(target, numpy.ndarray):
            # A view shares its pixels with the array it was cut from.
            if isinstance(target, SourcedArray):
                tag(target, (*sources_of(target), *extra))
            target = target.base

    def __reduce__(self):
        # Pickles and np.save as a plain array.
        return self.view(numpy.ndarray).__reduce__()


# Printed like any other array: repr() names the class.
SourcedArray.__name__ = "array"


def _plain(value: Any) -> Any:
    return value.view(numpy.ndarray) if isinstance(value, SourcedArray) else value


def _retag(result: Any, keys: tuple[Key, ...]) -> Any:
    if not keys:
        return result
    if isinstance(result, numpy.ndarray):
        return tag(result.view(SourcedArray), keys)
    if isinstance(result, tuple):
        return tuple(_retag(r, keys) for r in result)
    if isinstance(result, list):
        return [_retag(r, keys) for r in result]
    return result


def _array_entry(func):
    """np.array / np.asarray: an array made from a tagged image keeps its tag."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return _retag(func(*args, **kwargs), _collect((*args[:1], kwargs.get("object"), kwargs.get("a"))))
    return wrapper


def sandbox_numpy() -> types.ModuleType:
    """NumPy as agent code imports it: the real module, except that turning a
    tagged image into an array yields an array carrying that tag."""
    module = types.ModuleType("numpy")
    module.__dict__.update(numpy.__dict__)
    for name in ("array", "asarray", "asanyarray", "ascontiguousarray"):
        setattr(module, name, _array_entry(getattr(numpy, name)))
    return module


# --- Pillow -------------------------------------------------------------------

def _file_key(fp: Any) -> str | None:
    if not isinstance(fp, (str, os.PathLike)):
        return None
    from .file_sources import file_digest
    return file_digest(Path(os.fspath(fp)))


def _combining(func):
    """The result carries the tags of every image (or array) passed in."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        keys = _collect((*args, *kwargs.values()))
        if keys:
            # In-place methods (paste, putalpha) return None: the receiver is args[0].
            tag(result if isinstance(result, Image.Image) else args[0], keys)
        return result
    return wrapper


def _install() -> None:
    if getattr(Image, "_stimma_source_tags", False):
        return
    Image._stimma_source_tags = True

    new = Image.Image._new

    @functools.wraps(new)
    def _new(self, im):
        return tag(new(self, im), sources_of(self))
    Image.Image._new = _new

    opener = Image.open

    @functools.wraps(opener)
    def _open(fp, *args, **kwargs):
        image = opener(fp, *args, **kwargs)
        state = _current.get()
        if state is not None:
            key = _file_key(fp)
            if key:
                state.opened = True
                tag(image, (key,))
        return image
    Image.open = _open

    save = Image.Image.save

    @functools.wraps(save)
    def _save(self, fp, *args, **kwargs):
        result = save(self, fp, *args, **kwargs)
        state = _current.get()
        if state is not None and isinstance(fp, (str, os.PathLike)):
            keys = _collect([self, list(kwargs.get("append_images") or [])])
            if keys:
                try:
                    from .file_sources import note_written
                    note_written(state.workspace_dir, Path(os.fspath(fp)), keys)
                except Exception as e:  # A record, never a reason to fail the save.
                    log.warning(f"[source-tags] could not record sources of {fp}: {e}")
        return result
    Image.Image.save = _save

    # Operations that build a new image without going through _new, or that
    # mix several images.
    for name in ("paste", "putalpha", "transform"):
        setattr(Image.Image, name, _combining(getattr(Image.Image, name)))
    for name in ("alpha_composite", "blend", "composite", "merge", "fromarray"):
        setattr(Image, name, _combining(getattr(Image, name)))
    for name in ("add", "add_modulo", "blend", "composite", "darker", "difference", "hard_light",
                 "lighter", "logical_and", "logical_or", "logical_xor", "multiply", "overlay",
                 "screen", "soft_light", "subtract", "subtract_modulo"):
        setattr(ImageChops, name, _combining(getattr(ImageChops, name)))


_install()
