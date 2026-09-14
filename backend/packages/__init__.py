"""Packages: deliverables built from library assets by deterministic recipes.

A package is a ``.stimmapackage`` directory bundle: a manifest, member assets
copied in by content hash, zero or more recipe runs (each owning a subtree of
derivative files), optional loose extras, and a cover page (``index.html``).

Modules:
- ``manifest``   the on-disk format and its validation
- ``naming``     filename templates (a parameter type, never a function)
- ``recipes``    the recipe SDK, registry and runner
- ``cache``      run memoization with retention rules
- ``cover``      the cover page: kit, lint, auto cover, single-file inlining
- ``bundle``     building, saving, rebuilding and staleness
- ``export``     zip and single-file exports
"""
