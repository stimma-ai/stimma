"""Built-in recipes. Importing this package registers them."""

from packages.recipes import register_builtin

from . import app_icons, key_art_crops, logo, logo_exports, palette

for _module in (app_icons, logo, key_art_crops, logo_exports, palette):
    for _value in vars(_module).values():
        _spec = getattr(_value, "_stimma_recipe", None)
        if _spec is not None:
            register_builtin(_spec)
