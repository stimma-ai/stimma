"""Elements: reusable creative ingredients (a character, product, place, style or brand).

An element is an ``element`` Asset whose revisions are ``.stimmaelement`` bundles:
a thin manifest (``element.json``), instructions (``ELEMENT.md``) with block
conditionals, and companion files. Its media menu links library Assets.

Modules:
- ``manifest``   the bundle format and its validation
- ``template``   the ELEMENT.md conditional evaluator
- ``bundle``     committing and reading revisions
- ``workspace``  chat workspace checkouts under ``elements/<slug>/``
- ``lineage``    which element revisions a generated Media was made with
"""
