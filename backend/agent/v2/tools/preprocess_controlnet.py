"""Preprocess a reference image for controlnet workflows."""

import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..tools_registry import tool, ToolParameter

from core.logging import get_logger
from core.profile_context import get_current_profile
from database import MediaItem

log = get_logger(__name__)

CONTROLNET_PREPROCESSORS = {"canny", "depth", "lineart", "lineart_realistic", "lineart_anime", "pose", "pose_hands"}


async def _resolve_media_path(session: AsyncSession, media_id: int) -> str:
    """Resolve media_id to its file path."""
    result = await session.execute(
        select(MediaItem.file_path).where(MediaItem.id == media_id)
    )
    row = result.one_or_none()
    if not row or not row[0]:
        raise ValueError(f"Media {media_id} not found or has no file path")
    return row[0]


async def execute_preprocess_controlnet(
    media_id: int,
    preprocessor: str,
    params: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Run controlnet preprocessing and copy result to workspace.

    Returns dict with preprocessed_path, original_media_id, preprocessor, width, height.
    """
    session: AsyncSession = kwargs.get("session")
    if not session:
        raise ValueError("No database session available")

    workspace_dir = kwargs.get("workspace_dir")

    if preprocessor not in CONTROLNET_PREPROCESSORS:
        raise ValueError(
            f"Unknown preprocessor '{preprocessor}'. "
            f"Available: {', '.join(sorted(CONTROLNET_PREPROCESSORS))}"
        )

    # Resolve media_id → file path
    source_path = await _resolve_media_path(session, media_id)

    # Run preprocessing (reuses existing cache system)
    from controlnet import preprocess
    output_path, width, height = await preprocess(source_path, preprocessor, params)

    # Copy to workspace so the agent can reference it
    workspace_path = output_path
    if workspace_dir:
        filename = f"controlnet_{preprocessor}_{media_id}_{os.path.basename(output_path)}"
        workspace_path = os.path.join(str(workspace_dir), filename)
        shutil.copy2(output_path, workspace_path)

    return {
        "preprocessed_path": workspace_path,
        "original_media_id": media_id,
        "preprocessor": preprocessor,
        "preprocessor_params": params,
        "width": width,
        "height": height,
    }


@tool(
    name="preprocess_controlnet",
    description=(
        "Preprocess a reference image for controlnet (edge detection, depth, pose, etc.). "
        "Returns a preprocessed control map to pass as input_images to call_tool."
    ),
    parameters=[
        ToolParameter(
            name="media_id",
            type="integer",
            description="Media ID of source image",
        ),
        ToolParameter(
            name="preprocessor",
            type="string",
            description="Preprocessor type: canny, depth, lineart, lineart_realistic, lineart_anime, pose, pose_hands",
            enum=["canny", "depth", "lineart", "lineart_realistic", "lineart_anime", "pose", "pose_hands"],
        ),
        ToolParameter(
            name="params",
            type="object",
            description="Optional preprocessor params (e.g. {low: 100, high: 200} for canny)",
            required=False,
        ),
    ],
)
async def preprocess_controlnet(
    media_id: int,
    preprocessor: str,
    params: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> str:
    try:
        result = await execute_preprocess_controlnet(
            media_id=media_id,
            preprocessor=preprocessor,
            params=params,
            **kwargs,
        )
    except Exception as e:
        return f"Error: {e}"

    return (
        f"Preprocessed '{preprocessor}' control map from media_id={media_id}: "
        f"{result['preprocessed_path']} ({result['width']}x{result['height']})\n"
        f"Pass this path in `input_images` and set "
        f"`_original_input_paths=[{media_id}]`, "
        f"`_input_preprocessors=['{preprocessor}']` "
        f"in the inputs to call_tool for correct lineage tracking."
    )
