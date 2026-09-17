"""Fixture recipe: a square tile per requested platform, built through the pack's lib."""
import io

from packages.recipes import Build, Input, Param, recipe
from tilekit import tile

PLATFORMS = ("ios", "android", "web")


@recipe(
    id="tiles", version=1, display_name="Tiles",
    description="Fixture: one 256px tile per platform from a square master",
    inputs=[Input("master", kind="image", square=True, min_size=64, description="Square master artwork")],
    params=[
        Param("platforms", type="multi", options=list(PLATFORMS), default=list(PLATFORMS)),
        Param("background", type="color", default="#FFFFFF"),
        Param("app_name", type="string", default=None),
    ],
    guidance="Fixture recipe. See references/tiles for the tilekit lib it imports.",
)
async def build(b: Build) -> None:
    for platform in b.params.platforms:
        img = tile(await b.image("master", size=512), 256, b.params.background)
        buf = io.BytesIO(); img.save(buf, format="PNG")
        b.derive(f"{platform}/tile-256.png", buf.getvalue(), source="master")
    b.file("README.txt", f"Tiles for {b.params.app_name or b.slug}: {', '.join(b.params.platforms)}\n")
