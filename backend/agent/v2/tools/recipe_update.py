"""recipe_update — update recipe metadata from inside a recipe chat.

The recipe agent uses this tool to update ``name`` and ``description``.
Input/output schemas are NOT set here — ``program.py`` is the single
source of truth for those: the graph builder reads ``@recipe(inputs=...,
outputs=...)`` and ``recipe_lifecycle`` mirrors the serialized specs into
``Recipe.input_schema`` / ``Recipe.output_schema`` after every build.

Input values are normally supplied by the user through the inputs form in
the UI, which starts execution — the agent only passes ``inputs`` when
the user explicitly hands it values. When ``inputs`` is set on an idle
recipe, execution auto-starts.

Only usable inside a chat whose ``recipe_id`` is set. Used outside a
recipe chat it returns an informative error rather than silently no-op'ing.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select

import recipe_lifecycle
import recipe_registry
from database import Chat, Recipe
from utils.websocket import ws_manager

from ..tools_registry import tool, ToolParameter


@tool(
    name="recipe_update",
    description=(
        "Update this recipe's name or description. Input/output schemas are "
        "declared inside program.py via @recipe(inputs=..., outputs=...) "
        "and sync automatically — don't set them here. Only available in "
        "recipe chats. The `inputs` field is for the user — they fill the "
        "inputs form in the UI. Only pass `inputs` here if the user "
        "explicitly hands you values to set."
    ),
    parameters=[
        ToolParameter(
            name="name",
            type="string",
            description="Display name for the recipe.",
            required=False,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="One-paragraph description of what the recipe produces.",
            required=False,
        ),
        ToolParameter(
            name="inputs",
            type="object",
            description=(
                "Input values keyed by input name. The user fills these in "
                "through the inputs form in the UI — pass this field only "
                "when the user explicitly gives you values to set."
            ),
            required=False,
        ),
    ],
    scope="recipe",
)
async def recipe_update(
    name: str | None = None,
    description: str | None = None,
    inputs: dict | None = None,
    **kwargs,
) -> str:
    session = kwargs.get("session")
    chat_id = kwargs.get("chat_id")
    if session is None or chat_id is None:
        return "Error: recipe_update requires an active chat session."

    chat_row = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = chat_row.scalar_one_or_none()
    if chat is None:
        return f"Error: chat {chat_id} not found."
    if chat.recipe_id is None:
        return (
            "Error: this chat is not attached to a recipe. recipe_update is only "
            "usable in recipe chats. Create a recipe first via POST /api/recipes "
            "and open its chat."
        )

    recipe_row = await session.execute(
        select(Recipe).where(Recipe.id == chat.recipe_id, Recipe.deleted_at.is_(None))
    )
    recipe = recipe_row.scalar_one_or_none()
    if recipe is None:
        return f"Error: recipe {chat.recipe_id} not found or deleted."

    changed: list[str] = []
    if name is not None:
        recipe.name = name.strip()
        changed.append("name")
    if description is not None:
        recipe.description = description
        changed.append("description")
    if inputs is not None:
        recipe.inputs = json.dumps(inputs)
        changed.append("inputs")

    if not changed:
        return (
            "No fields provided. Pass at least one of: name, description, "
            "inputs. (Input/output schemas come from program.py.)"
        )

    await session.commit()
    await session.refresh(recipe)

    await ws_manager.broadcast(
        "recipe_updated",
        {"recipe": recipe.to_dict(), "fields_changed": changed},
    )

    started = False
    start_error: str | None = None
    if "inputs" in changed and recipe.execution_state == "idle":
        # Auto-start when inputs are set on an idle recipe so the runtime can
        # validate the graph and surface progress without a manual /start.
        try:
            runtime = recipe_lifecycle.get_or_create_runtime(recipe)
            await runtime.start()
            recipe.execution_state = "running"
            recipe.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(recipe)
            await ws_manager.broadcast(
                "recipe_updated",
                {"recipe": recipe.to_dict(), "fields_changed": ["execution_state"]},
            )
            started = True
        except Exception as exc:  # noqa: BLE001
            start_error = str(exc)

    suffix = ""
    if "inputs" in changed:
        if started:
            suffix = (
                " Recipe started — progress and HITL tasks will surface in the "
                "recipe UI."
            )
        elif start_error:
            suffix = f" Inputs stored but auto-start failed: {start_error}"
        else:
            suffix = " Inputs stored."

    return f"Recipe {recipe.id} updated ({', '.join(changed)}).{suffix}"
