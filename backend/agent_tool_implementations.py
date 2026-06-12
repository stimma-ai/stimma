"""
Implementations of agent tools.
"""
import math
import random
import json
import asyncio
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from PIL import Image

from agent_tools import tool
from database import Chat, ChatItem, GenerationJob
from config import get_settings
from core.profile_context import get_current_profile
from core.logging import get_logger
from utils.websocket import ws_manager

log = get_logger(__name__)


def compute_size_from_image(image_path: str, megapixels: float, step: int = 64) -> Tuple[int, int]:
    """Compute output size from input image aspect ratio and target megapixels.

    Args:
        image_path: Path to the input image
        megapixels: Target megapixels for output
        step: Round dimensions to this value (default 64 for most models, use 16 for video)

    Returns:
        Tuple of (width, height) rounded to nearest step
    """
    from utils.image_ops import open_oriented
    with open_oriented(image_path) as img:
        src_width, src_height = img.size

    aspect_ratio = src_width / src_height
    target_pixels = megapixels * 1_000_000

    # Calculate dimensions that maintain aspect ratio and hit target megapixels
    # width * height = target_pixels
    # width / height = aspect_ratio
    # Therefore: width = sqrt(target_pixels * aspect_ratio)
    width = math.sqrt(target_pixels * aspect_ratio)
    height = width / aspect_ratio

    # Round to nearest step
    width = round(width / step) * step
    height = round(height / step) * step

    # Ensure minimum dimensions
    min_dim = step * 4  # e.g., 256 for step=64
    width = max(min_dim, width)
    height = max(min_dim, height)

    return (int(width), int(height))


def get_chat_resolution_override(chat: Chat) -> Optional[Tuple[int, int]]:
    """Get the resolution override from the chat's generation_settings if present.

    Returns:
        Tuple of (width, height) if override is set, default (848, 1152) if chat exists but no resolution set,
        or None if no chat.
    """
    # Default resolution matching frontend defaults (ChatView.vue, ResolutionPicker.vue)
    DEFAULT_WIDTH = 848
    DEFAULT_HEIGHT = 1152

    if not chat:
        return None

    if not chat.generation_settings:
        # Chat exists but no generation_settings - return the default
        # This matches what the UI shows for new chats
        log.info(f"[get_chat_resolution_override] No generation_settings on chat, using default {DEFAULT_WIDTH}x{DEFAULT_HEIGHT}")
        return (DEFAULT_WIDTH, DEFAULT_HEIGHT)

    try:
        settings = json.loads(chat.generation_settings) if isinstance(chat.generation_settings, str) else chat.generation_settings
        log.info(f"[get_chat_resolution_override] Parsed settings keys: {list(settings.keys())}")
        resolution = settings.get("resolution")
        log.info(f"[get_chat_resolution_override] Resolution from settings: {resolution}")
        if resolution and isinstance(resolution, dict):
            width = resolution.get("width")
            height = resolution.get("height")
            if width and height:
                log.info(f"[get_chat_resolution_override] Returning override: {width}x{height}")
                return (int(width), int(height))
        # Chat has generation_settings but no resolution key - return the default
        log.info(f"[get_chat_resolution_override] No resolution in settings, using default {DEFAULT_WIDTH}x{DEFAULT_HEIGHT}")
        return (DEFAULT_WIDTH, DEFAULT_HEIGHT)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        log.warning(f"[get_chat_resolution_override] Error parsing settings: {e}")
        return (DEFAULT_WIDTH, DEFAULT_HEIGHT)


async def get_tool_selection_for_task(session, chat: Chat, task_type: str) -> Optional[Dict[str, Any]]:
    """Get the tool selection for a task type from chat's toolSelections.

    New provider-based approach:
    1. Read toolSelections from chat.generation_settings
    2. Check agent_tool_config for allowed_tools constraints
    3. Get the provider tool by fullToolId (preferring allowed tools)
    4. If a presetId is set, load the preset state
    5. Return combined settings

    Returns: Dict with fullToolId, presetId, providerTool info, and merged state, or None.
    """
    from providers import ProviderRegistry
    from database import Preset

    registry = ProviderRegistry()

    # Parse agent_tool_config for allowed_tools
    allowed_tools = []
    if chat.agent_tool_config:
        try:
            tool_config = json.loads(chat.agent_tool_config)
            allowed_tools = tool_config.get("allowed_tools", [])
            log.info(f"[get_tool_selection_for_task] Chat {chat.id} allowed_tools: {allowed_tools}")
        except json.JSONDecodeError:
            pass

    # Parse generation_settings
    gen_settings = {}
    if chat.generation_settings:
        try:
            gen_settings = json.loads(chat.generation_settings)
            log.info(f"[get_tool_selection_for_task] Chat {chat.id} gen_settings keys: {list(gen_settings.keys())}")
        except json.JSONDecodeError:
            log.warning(f"[get_tool_selection_for_task] Failed to parse generation_settings")
    else:
        log.info(f"[get_tool_selection_for_task] Chat {chat.id} has no generation_settings")

    tool_selections = gen_settings.get("toolSelections", {})
    log.info(f"[get_tool_selection_for_task] toolSelections for chat {chat.id}: {tool_selections}")
    selection = tool_selections.get(task_type)
    log.info(f"[get_tool_selection_for_task] Selection for {task_type}: {selection}")

    # Helper to find an allowed tool for this task type
    def find_allowed_tool_for_task():
        """Find a tool from allowed_tools that supports this task_type."""
        if not allowed_tools:
            return None
        tools_for_task = registry.list_tools_by_task_type(task_type)
        for full_tool_id, provider, tool in tools_for_task:
            if full_tool_id in allowed_tools:
                log.info(f"[get_tool_selection_for_task] Found allowed tool for {task_type}: {full_tool_id}")
                return {
                    "fullToolId": full_tool_id,
                    "presetId": None,
                    "providerTool": tool,
                    "providerId": provider.provider_id,
                    "providerName": provider.provider_name or provider.provider_id,
                    "state": {},  # Use tool defaults
                }
        return None

    if not selection:
        log.info(f"[get_tool_selection_for_task] No explicit selection for {task_type}")
        # First try to use an allowed tool if allowed_tools has entries
        if allowed_tools:
            allowed_result = find_allowed_tool_for_task()
            if allowed_result:
                return allowed_result
            log.info(f"[get_tool_selection_for_task] No allowed tools support {task_type}, falling back to first available")

        # Fall back to first provider tool for this task type
        tools_for_task = registry.list_tools_by_task_type(task_type)
        if tools_for_task:
            full_tool_id, provider, tool = tools_for_task[0]
            log.info(f"[get_tool_selection_for_task] Using first available tool: {full_tool_id}")
            return {
                "fullToolId": full_tool_id,
                "presetId": None,
                "providerTool": tool,
                "providerId": provider.provider_id,
                "providerName": provider.provider_name or provider.provider_id,
                "state": {},  # Use tool defaults
            }
        return None

    full_tool_id = selection.get("fullToolId")
    preset_id = selection.get("presetId")

    if not full_tool_id:
        log.warning(f"[get_tool_selection_for_task] Selection for {task_type} has no fullToolId")
        return None

    # If allowed_tools has entries and the selected tool is not in it, it will need permission
    # Don't silently substitute - let the permission flow handle it so user can choose
    if allowed_tools and full_tool_id not in allowed_tools:
        log.info(f"[get_tool_selection_for_task] Selected tool {full_tool_id} not in allowed_tools, will require permission")

    log.info(f"[get_tool_selection_for_task] Looking up tool: {full_tool_id}, presetId: {preset_id}")

    # Find the provider tool using registry cache
    tool_entry = registry.get_tool(full_tool_id)
    if not tool_entry:
        log.warning(f"[get_tool_selection_for_task] Provider tool not found: {full_tool_id}")
        return None

    provider, provider_tool = tool_entry

    # Load preset state if one is selected
    preset_state = {}
    if preset_id:
        result = await session.execute(
            select(Preset).where(
                Preset.id == preset_id,
                Preset.deleted_at.is_(None)
            )
        )
        preset = result.scalar_one_or_none()
        if preset and preset.state:
            try:
                preset_state = json.loads(preset.state)
                log.info(f"[get_tool_selection_for_task] Loaded preset '{preset.name}' (id={preset_id})")
                log.info(f"[get_tool_selection_for_task] Preset state keys: {list(preset_state.keys())}")
                log.info(f"[get_tool_selection_for_task] Preset state values: steps={preset_state.get('steps')}, cfg={preset_state.get('cfg')}, loras={preset_state.get('loras', 'NOT PRESENT')}")
            except json.JSONDecodeError:
                log.warning(f"[get_tool_selection_for_task] Failed to parse preset state for id={preset_id}")
        elif preset:
            log.warning(f"[get_tool_selection_for_task] Preset '{preset.name}' (id={preset_id}) has empty/null state")
        else:
            log.warning(f"[get_tool_selection_for_task] Preset not found for id={preset_id}")

    return {
        "fullToolId": full_tool_id,
        "presetId": preset_id,
        "providerTool": provider_tool,
        "providerId": provider.provider_id,
        "providerName": provider.provider_name or provider.provider_id,
        "state": preset_state,
    }


def get_settings_from_provider_tool(tool_selection: Dict[str, Any]) -> Dict[str, Any]:
    """Extract generation settings from a provider tool + optional preset state.

    Args:
        tool_selection: Dict from get_tool_selection_for_task()

    Returns: Dict with generator, model, parameters, loras, output_folder
    """
    provider_tool = tool_selection["providerTool"]
    preset_state = tool_selection.get("state", {})

    # Parse the full_tool_id to extract generator and model info
    # Format: "builtin:comfyui:model-name:task-type" or similar
    full_tool_id = tool_selection["fullToolId"]
    parts = full_tool_id.split(":")

    # Get defaults from the provider tool's single parameter_schema
    # (contains prompt, width, height, seed, steps, cfg, sampler, scheduler, etc.)
    tool_defaults = {}
    if provider_tool.parameter_schema:
        for param_name, param_def in provider_tool.parameter_schema.get("properties", {}).items():
            if "default" in param_def:
                tool_defaults[param_name] = param_def["default"]

    # Also check metadata for additional defaults
    if provider_tool.metadata:
        for key in ["width", "height", "cfg", "steps", "sampler", "scheduler", "megapixels",
                    "fps", "frame_count", "scale_factor", "resolution", "denoise", "shift"]:
            if key in provider_tool.metadata:
                tool_defaults[key] = provider_tool.metadata[key]

    # Merge: tool defaults <- preset state (preset overrides tool defaults)
    state = {**tool_defaults, **preset_state}
    log.info(f"[get_settings_from_provider_tool] tool_defaults keys: {list(tool_defaults.keys())}")
    log.info(f"[get_settings_from_provider_tool] preset_state keys: {list(preset_state.keys())}")
    log.info(f"[get_settings_from_provider_tool] Merged state: steps={state.get('steps')}, cfg={state.get('cfg')}, loras count={len(state.get('loras', []))}")

    # Extract generator and model from tool metadata or full_tool_id
    # Metadata uses "generator_name" and "model_name" (set by tool providers)
    generator = provider_tool.metadata.get("generator_name") if provider_tool.metadata else None
    model = provider_tool.metadata.get("model_name") if provider_tool.metadata else None

    # Fall back to parsing from tool name/id if not in metadata
    if not generator and len(parts) >= 2:
        generator = parts[1]  # e.g., "comfyui" from "builtin:comfyui:..."
    if not model:
        model = provider_tool.name  # Use tool name as model identifier

    output_folder = state.get("folder_path")

    # Build parameters from state
    merged_params = {
        "width": state.get("width"),
        "height": state.get("height"),
        "cfg": state.get("cfg"),
        "steps": state.get("steps"),
        "sampler": state.get("sampler"),
        "scheduler": state.get("scheduler"),
        "denoise": state.get("denoise"),
        "shift": state.get("shift"),
        "negative_prompt": state.get("negative_prompt", ""),
    }

    # Pass through task-specific parameters (normalize keys)
    for key in ["megapixels", "fps", "frameCount", "frame_count", "scale_factor", "scaleFactor",
                "resolution", "targetResolution", "resolutionMode", "colorCorrection", "color_correction",
                "guidance", "lightning"]:
        if key in state:
            normalized_key = key
            if key == "frameCount":
                normalized_key = "frame_count"
            elif key == "scaleFactor":
                normalized_key = "scale_factor"
            elif key == "targetResolution":
                normalized_key = "target_resolution"
            elif key == "resolutionMode":
                normalized_key = "resolution_mode"
            elif key == "colorCorrection":
                normalized_key = "color_correction"
            merged_params[normalized_key] = state[key]

    # Get LoRAs - only include enabled ones
    loras = []
    if "loras" in state:
        for lora_entry in state["loras"]:
            if lora_entry.get("enabled", True):
                loras.append({
                    "lora": lora_entry.get("lora"),
                    "weight": lora_entry.get("weight", 1.0)
                })

    result = {
        "generator": generator,
        "model": model,
        "parameters": merged_params,
        "loras": loras,
        "output_folder": output_folder,
        "full_tool_id": full_tool_id,
        "tool_name": provider_tool.name,
        "provider_name": tool_selection.get("providerName"),
        "preset_id": tool_selection.get("presetId"),
    }
    log.info(f"[get_settings_from_provider_tool] Final result: params.steps={merged_params.get('steps')}, loras count={len(loras)}")
    return result


async def get_generation_settings_for_task(session, chat: Chat, task_type: str) -> Optional[Dict[str, Any]]:
    """Get generation settings for a task, trying new provider-based approach first.

    This is the unified entry point for getting generation settings.
    Uses the provider-based toolSelections approach.

    Returns: Dict with generator, model, parameters, loras, output_folder, etc.
             or None if no suitable tool found.
    """
    tool_selection = await get_tool_selection_for_task(session, chat, task_type)
    if tool_selection:
        log.info(f"[get_generation_settings_for_task] Using provider tool: {tool_selection['fullToolId']}")
        return get_settings_from_provider_tool(tool_selection)

    return None


# Define the prompts parameter schema for the generate tool
PROMPTS_SCHEMA = {
    "description": "Array of prompts to generate images for. Each item has 'text' (the prompt) and optional 'n' (number of images, default 1).",
    "items_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text prompt to generate images for"
            },
            "n": {
                "type": "integer",
                "description": "Number of images to generate for this prompt (default 1)"
            }
        },
        "required": ["text"]
    }
}


@tool(name="generate",
      description="""Generate images from one or more text prompts.

Use the 'prompts' parameter with an array of objects:
- Each object has 'text' (the prompt) and optional 'n' (image count, default 1)

Examples:
- Single prompt, 1 image: prompts=[{"text": "a cat"}]
- Single prompt, 5 images: prompts=[{"text": "a cat", "n": 5}]
- Multiple prompts: prompts=[{"text": "a cat", "n": 3}, {"text": "a dog", "n": 2}]

Images generate in the background - do not say generation is complete, only that it has started.""",
      injected_params=["chat_id", "session"],
      param_schemas={"prompts": PROMPTS_SCHEMA})
async def generate(
    chat_id: int,
    session: AsyncSession,
    prompts: list,
) -> dict:
    """
    Generates images using the current generation parameters.

    Args:
        prompts: Array of prompt objects, each with 'text' and optional 'n' (default 1).

    Returns: {
        "status": "started",
        "message": str,
        "count": int,
        "success": bool
    }
    """
    try:
        # Handle prompts being passed as a JSON string (some models do this)
        if isinstance(prompts, str):
            try:
                prompts = json.loads(prompts)
            except json.JSONDecodeError:
                return {"error": "Invalid prompts format. Expected array of objects.", "success": False}

        # Validate prompts
        if not prompts or not isinstance(prompts, list) or len(prompts) == 0:
            return {"error": "No prompts provided. Use prompts=[{\"text\": \"your prompt\"}]", "success": False}

        # Normalize and validate each prompt
        normalized_prompts = []
        for p in prompts:
            if isinstance(p, str):
                # Allow simple string prompts
                normalized_prompts.append({"text": p.strip(), "n": 1})
            elif isinstance(p, dict):
                text = p.get("text", "").strip() if isinstance(p.get("text"), str) else ""
                if not text:
                    return {"error": "Each prompt must have a non-empty 'text' field", "success": False}
                n = p.get("n", 1)
                if isinstance(n, str):
                    n = int(n) if n.strip() else 1
                if not n or n < 1:
                    n = 1
                normalized_prompts.append({"text": text, "n": n})
            else:
                return {"error": "Each prompt must be a string or object with 'text' field", "success": False}

        total_jobs = sum(p["n"] for p in normalized_prompts)
        log.info(f"generate: {len(normalized_prompts)} prompts, {total_jobs} total images")

        settings = get_settings()

        # Get chat
        result = await session.execute(select(Chat).where(Chat.id == chat_id))
        chat = result.scalar_one_or_none()

        if not chat:
            log.error(f"Chat {chat_id} not found in generate")
            return {"error": "Chat not found", "success": False}

        # Get the appropriate tool for text-to-image
        gen_settings = await get_generation_settings_for_task(session, chat, "text-to-image")
        if not gen_settings:
            log.error("No text-to-image tool configured")
            return {"error": "No text-to-image tool configured. Please configure a tool first.", "success": False}

        params = gen_settings["parameters"]
        final_loras = gen_settings.get("loras", [])

        # Apply chat's resolution override if present (overrides tool-specified resolution)
        resolution_override = get_chat_resolution_override(chat)
        if resolution_override:
            params["width"], params["height"] = resolution_override
            log.info(f"Using chat resolution override: {params['width']}x{params['height']}")

        # Get output folder - prefer from settings, fall back to first generation folder
        output_folder = gen_settings.get("output_folder")
        if not output_folder:
            generation_folders = settings.get_generation_folders_for_profile(get_current_profile())
            if not generation_folders:
                log.error("No generation folders configured")
                return {"error": "No generation folders configured", "success": False}
            output_folder = generation_folders[0].path

        # Get generator and model from settings
        generator_name = gen_settings.get("generator")
        model_name = gen_settings.get("model")

        # Find the configured generator
        generator = None
        if generator_name:
            generator = next((g for g in settings.generators if g.name == generator_name), None)

        # Fall back to first generator if not found
        if not generator:
            if not settings.generators:
                log.error("No generators configured")
                return {"error": "No generators configured", "success": False}
            generator = settings.generators[0]
            log.warning(f"Configured generator '{generator_name}' not found, using first: {generator.name}")

        # Model must come from tool
        if not model_name:
            log.error("No model configured in tool")
            return {"error": "No model configured in tool", "success": False}

        log.info(f"Using generator: {generator.type}/{generator.name}, model: {model_name}")

        # Create generation jobs for all prompts
        all_job_ids = []
        prompt_groups = []

        for prompt_obj in normalized_prompts:
            prompt_text = prompt_obj["text"]
            n = prompt_obj["n"]

            # Generate base seed for this prompt
            base_seed = random.randint(0, 2**32 - 1)

            prompt_job_ids = []
            prompt_seeds = []

            for i in range(n):
                current_seed = base_seed + i

                log.info(f"Creating job for prompt '{prompt_text[:50]}...' with seed {current_seed}")

                # Build parameters JSON using current parameters
                parameters = {
                    "prompt": prompt_text,
                    "negative_prompt": params["negative_prompt"],
                    "width": params["width"],
                    "height": params["height"],
                    "cfg": params["cfg"],
                    "steps": params["steps"],
                    "sampler": params["sampler"],
                    "scheduler": params["scheduler"],
                    "denoise": params["denoise"],
                    "shift": params["shift"],
                    "seed": current_seed,
                    "loras": final_loras
                }

                job = GenerationJob(
                    status="queued",
                    task_type="text-to-image",
                    generator_type=generator.type,
                    generator_name=generator.name,
                    backend_name=generator.name,
                    model_name=model_name,
                    parameters=json.dumps(parameters),
                    folder_path=output_folder,
                    auto_delete_duration=gen_settings.get("auto_delete_duration", "1h"),
                    generator_instance_id=f"chat-{chat_id}",

                )

                session.add(job)
                await session.flush()

                prompt_job_ids.append(job.id)
                prompt_seeds.append(current_seed)
                all_job_ids.append(job.id)

            # Store prompt group info
            prompt_groups.append({
                "text": prompt_text,
                "n": n,
                "job_ids": prompt_job_ids,
                "seeds": prompt_seeds
            })

        log.info(f"Created {len(all_job_ids)} generation jobs: {all_job_ids}")
        await session.commit()

        # Create a generation_grid chat item with all job IDs and prompt grouping
        grid_data = {
            "job_ids": all_job_ids,
            "prompts": prompt_groups,
            "total_count": total_jobs,
            "full_tool_id": gen_settings.get("full_tool_id"),
            "tool_name": gen_settings.get("tool_name"),
            "preset_id": gen_settings.get("preset_id"),
        }

        grid_item = ChatItem(
            chat_id=chat_id,
            item_type="generation_grid",
            grid_layout=json.dumps(grid_data)
        )
        session.add(grid_item)
        await session.flush()

        log.info(f"Created generation_grid ChatItem with id={grid_item.id}, jobs={all_job_ids}")

        # Broadcast the grid item immediately
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": grid_item.to_dict()
        })

        # Return immediately - generation happens in background
        log.info(f"Returning immediately with {len(all_job_ids)} job IDs")
        return {
            "status": "queued",
            "count": total_jobs,
            "success": True,
            "action_complete": True,
            "message": f"Queued {total_jobs} image(s) for generation. Request fulfilled - do not generate more unless user asks.",
        }
    except Exception as e:
        log.error(f"generate failed with exception: {str(e)}", exc_info=True)
        return {
            "error": str(e),
            "success": False
        }


# Define the images parameter schema for the edit_image tool
IMAGES_SCHEMA = {
    "description": "Array of media IDs of images to use as reference/input for editing.",
    "items_schema": {
        "type": "integer",
        "description": "Media ID of an image"
    }
}


@tool(name="edit_image",
      description="""Edit or transform images using AI. Takes one or more reference images and a prompt describing the desired result.

Parameters:
- image_ids: Array of media IDs to use as reference images (required, 1-10 images)
- prompt: Description of the desired output image (required)
- n: Number of variations to generate (optional, default 1)

Examples:
- Edit single image: image_ids=[123], prompt="make it look like a painting"
- Combine multiple references: image_ids=[123, 456], prompt="combine these styles"

Images generate in the background - do not say generation is complete, only that it has started.""",
      injected_params=["chat_id", "session"],
      param_schemas={"image_ids": IMAGES_SCHEMA})
async def edit_image(
    chat_id: int,
    session: AsyncSession,
    image_ids: list,
    prompt: str,
    n: int = 1,
) -> dict:
    """
    Edit images using reference images and a prompt.

    Args:
        image_ids: Array of media IDs to use as input images.
        prompt: Description of the desired output.
        n: Number of variations to generate (default 1).

    Returns: {
        "status": "started",
        "message": str,
        "count": int,
        "success": bool
    }
    """
    try:
        # Handle image_ids being passed as a JSON string - be robust to LLM formatting issues
        if isinstance(image_ids, str):
            try:
                image_ids = json.loads(image_ids)
            except json.JSONDecodeError:
                # Try to extract numbers from malformed input like "[1][2][3]" or "1, 2, 3"
                import re
                numbers = re.findall(r'\d+', image_ids)
                if numbers:
                    image_ids = [int(n) for n in numbers]
                else:
                    return {"error": "Invalid image_ids format. Expected array of integers.", "success": False}

        # Ensure it's a list
        if not isinstance(image_ids, list):
            image_ids = [image_ids]

        # Convert all elements to integers
        try:
            image_ids = [int(mid) for mid in image_ids]
        except (ValueError, TypeError):
            return {"error": "Invalid image_ids values. Expected integers.", "success": False}

        # Validate image_ids
        if not image_ids or len(image_ids) == 0:
            return {"error": "No image_ids provided. Use image_ids=[media_id, ...]", "success": False}

        if len(image_ids) > 10:
            return {"error": "Maximum 10 input images supported", "success": False}

        # Validate prompt
        if not prompt or not str(prompt).strip():
            return {"error": "No prompt provided", "success": False}
        prompt = str(prompt).strip()

        # Validate n
        if isinstance(n, str):
            n = int(n) if n.strip() else 1
        if not n or n < 1:
            n = 1

        log.info(f"edit_image: {len(image_ids)} input images, prompt='{prompt[:50]}...', n={n}")

        settings = get_settings()

        # Get chat and generation settings
        result = await session.execute(select(Chat).where(Chat.id == chat_id))
        chat = result.scalar_one_or_none()

        if not chat:
            log.error(f"Chat {chat_id} not found in edit_image")
            return {"error": "Chat not found", "success": False}

        # Resolve media IDs to file paths
        from database import MediaItem
        input_image_paths = []
        for media_id in image_ids:
            media_result = await session.execute(select(MediaItem).where(MediaItem.id == media_id))
            media = media_result.scalar_one_or_none()
            if not media:
                return {"error": f"Media ID {media_id} not found", "success": False}
            input_image_paths.append(media.file_path)

        # Get the appropriate tool for image-to-image
        gen_settings = await get_generation_settings_for_task(session, chat, "image-to-image")
        if not gen_settings:
            log.error("No image-to-image tool configured")
            return {"error": "No image-to-image tool configured. Please configure a tool first.", "success": False}

        params = gen_settings["parameters"]
        final_loras = gen_settings.get("loras", [])

        # Get output folder
        output_folder = gen_settings.get("output_folder")
        if not output_folder:
            generation_folders = settings.get_generation_folders_for_profile(get_current_profile())
            if not generation_folders:
                log.error("No generation folders configured")
                return {"error": "No generation folders configured", "success": False}
            output_folder = generation_folders[0].path

        # Get generator and model from settings
        generator_name = gen_settings.get("generator")
        model_name = gen_settings.get("model")

        # Find the configured generator
        generator = None
        if generator_name:
            generator = next((g for g in settings.generators if g.name == generator_name), None)

        # Fall back to first generator if not found
        if not generator:
            if not settings.generators:
                log.error("No generators configured")
                return {"error": "No generators configured", "success": False}
            generator = settings.generators[0]
            log.warning(f"Configured generator '{generator_name}' not found, using first: {generator.name}")

        # Model must come from tool
        if not model_name:
            log.error("No model configured in tool")
            return {"error": "No model configured in tool", "success": False}

        log.info(f"Using generator: {generator.type}/{generator.name}, model: {model_name}")

        # Create generation jobs
        job_ids = []
        seeds = []
        base_seed = random.randint(0, 2**32 - 1)

        # Compute output size from first input image + megapixels
        megapixels = params.get("megapixels", 1.0)
        width, height = compute_size_from_image(input_image_paths[0], megapixels, step=64)

        for i in range(n):
            current_seed = base_seed + i

            # Build parameters JSON
            parameters = {
                "prompt": prompt,
                "negative_prompt": params.get("negative_prompt", ""),
                "width": width,
                "height": height,
                "megapixels": megapixels,
                "steps": params["steps"],
                "seed": current_seed,
                "input_images": input_image_paths,
                "input_media_ids": image_ids,  # Media IDs for lineage tracking
                "loras": final_loras,
                # Image edit specific params
                "guidance": params.get("cfg", 3.5),  # Flux uses guidance
            }

            job = GenerationJob(
                status="queued",
                task_type="image-to-image",
                generator_type=generator.type,
                generator_name=generator.name,
                backend_name=generator.name,
                model_name=model_name,
                parameters=json.dumps(parameters),
                folder_path=output_folder,
                auto_delete_duration=gen_settings.get("auto_delete_duration", "1h"),
                generator_instance_id=f"chat-{chat_id}",
            )

            session.add(job)
            await session.flush()

            job_ids.append(job.id)
            seeds.append(current_seed)

        log.info(f"Created {len(job_ids)} image-to-image jobs: {job_ids}")
        await session.commit()

        # Create a generation_grid chat item
        grid_data = {
            "job_ids": job_ids,
            "prompts": [{
                "text": prompt,
                "n": n,
                "job_ids": job_ids,
                "seeds": seeds
            }],
            "total_count": n,
            "task_type": "image-to-image",
            "input_image_ids": image_ids,

            "full_tool_id": gen_settings.get("full_tool_id"),
            "tool_name": gen_settings.get("tool_name"),
            "preset_id": gen_settings.get("preset_id"),
        }

        grid_item = ChatItem(
            chat_id=chat_id,
            item_type="generation_grid",
            grid_layout=json.dumps(grid_data)
        )
        session.add(grid_item)
        await session.flush()

        log.info(f"Created generation_grid ChatItem with id={grid_item.id}, jobs={job_ids}")

        # Broadcast the grid item immediately
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": grid_item.to_dict()
        })

        return {
            "status": "queued",
            "count": n,
            "success": True,
            "action_complete": True,
            "message": f"Queued {n} image edit(s). Request fulfilled - do not edit more unless user asks.",
        }
    except Exception as e:
        log.error(f"edit_image failed with exception: {str(e)}", exc_info=True)
        return {
            "error": str(e),
            "success": False
        }


@tool(name="image_to_video",
      description="""Generate a video from a starting image. Takes an image and animates it based on an optional prompt.

Parameters:
- image_id: Media ID of the starting image (required)
- prompt: Description of the motion/animation (optional but recommended)
- end_image_id: Media ID of an ending image for interpolation (optional)

Examples:
- Animate an image: image_id=123, prompt="the person waves hello"
- Interpolate between images: image_id=123, end_image_id=456, prompt="smooth transition"

Video generates in the background - do not say generation is complete, only that it has started.""",
      injected_params=["chat_id", "session"])
async def image_to_video(
    chat_id: int,
    session: AsyncSession,
    image_id: int,
    prompt: str = "",
    end_image_id: int = None,
) -> dict:
    """
    Generate a video from a starting image.

    Args:
        image_id: Media ID of the starting image.
        prompt: Description of the motion/animation (optional).
        end_image_id: Media ID of an ending image for interpolation (optional).

    Returns: {
        "status": "started",
        "message": str,
        "success": bool
    }
    """
    try:
        # Handle image_id being passed as string
        if isinstance(image_id, str):
            image_id = int(image_id)

        if isinstance(end_image_id, str):
            end_image_id = int(end_image_id) if end_image_id else None

        log.info(f"image_to_video: start_image={image_id}, end_image={end_image_id}, prompt='{prompt[:50] if prompt else ''}'")

        settings = get_settings()

        # Get chat
        result = await session.execute(select(Chat).where(Chat.id == chat_id))
        chat = result.scalar_one_or_none()

        if not chat:
            log.error(f"Chat {chat_id} not found in image_to_video")
            return {"error": "Chat not found", "success": False}

        # Resolve media IDs to file paths
        from database import MediaItem
        start_result = await session.execute(select(MediaItem).where(MediaItem.id == image_id))
        start_media = start_result.scalar_one_or_none()
        if not start_media:
            return {"error": f"Start image (media ID {image_id}) not found", "success": False}
        start_image_path = start_media.file_path

        end_image_path = None
        if end_image_id:
            end_result = await session.execute(select(MediaItem).where(MediaItem.id == end_image_id))
            end_media = end_result.scalar_one_or_none()
            if not end_media:
                return {"error": f"End image (media ID {end_image_id}) not found", "success": False}
            end_image_path = end_media.file_path

        # Get the appropriate tool for image-to-video
        gen_settings = await get_generation_settings_for_task(session, chat, "image-to-video")
        if not gen_settings:
            log.error("No image-to-video tool configured")
            return {"error": "No image-to-video tool configured. Please configure a tool first.", "success": False}

        params = gen_settings["parameters"]

        # Get output folder
        output_folder = gen_settings.get("output_folder")
        if not output_folder:
            generation_folders = settings.get_generation_folders_for_profile(get_current_profile())
            if not generation_folders:
                log.error("No generation folders configured")
                return {"error": "No generation folders configured", "success": False}
            output_folder = generation_folders[0].path

        # Get generator and model from settings
        generator_name = gen_settings.get("generator")
        model_name = gen_settings.get("model")

        # Find the configured generator
        generator = None
        if generator_name:
            generator = next((g for g in settings.generators if g.name == generator_name), None)

        # Fall back to first generator if not found
        if not generator:
            if not settings.generators:
                log.error("No generators configured")
                return {"error": "No generators configured", "success": False}
            generator = settings.generators[0]
            log.warning(f"Configured generator '{generator_name}' not found, using first: {generator.name}")

        # Model must come from tool
        if not model_name:
            log.error("No model configured in tool")
            return {"error": "No model configured in tool", "success": False}

        log.info(f"Using generator: {generator.type}/{generator.name}, model: {model_name}")

        # Generate seed
        seed = random.randint(0, 2**32 - 1)

        # Compute output size from start image + megapixels (use step=16 for video)
        megapixels = params.get("megapixels", 0.4)  # Default ~848x480 for 16:9
        width, height = compute_size_from_image(start_image_path, megapixels, step=16)

        # Build parameters JSON for image-to-video
        parameters = {
            "prompt": prompt or "",
            "negative_prompt": params.get("negative_prompt", ""),
            "width": width,
            "height": height,
            "frame_count": params.get("frame_count", 81),
            "fps": params.get("fps", 16),
            "cfg": params.get("cfg", 4.0),
            "steps": params.get("steps", 20),
            "sampler": params.get("sampler", "euler"),
            "scheduler": params.get("scheduler", "simple"),
            "shift": params.get("shift", 5.0),
            "seed": seed,
            "input_images": [start_image_path] + ([end_image_path] if end_image_path else []),
            "input_media_ids": [image_id] + ([end_image_id] if end_image_id else []),
            "lightning": params.get("lightning", False),
        }

        job = GenerationJob(
            status="queued",
            task_type="image-to-video",
            generator_type=generator.type,
            generator_name=generator.name,
            backend_name=generator.name,
            model_name=model_name,
            parameters=json.dumps(parameters),
            folder_path=output_folder,
            auto_delete_duration=gen_settings.get("auto_delete_duration", "1h"),
            generator_instance_id=f"chat-{chat_id}",
        )

        session.add(job)
        await session.flush()

        log.info(f"Created image-to-video job: {job.id}")
        await session.commit()

        # Create a generation_grid chat item
        grid_data = {
            "job_ids": [job.id],
            "prompts": [{
                "text": prompt or "(image animation)",
                "n": 1,
                "job_ids": [job.id],
                "seeds": [seed]
            }],
            "total_count": 1,
            "task_type": "image-to-video",
            "start_image_id": image_id,
            "end_image_id": end_image_id,

            "full_tool_id": gen_settings.get("full_tool_id"),
            "tool_name": gen_settings.get("tool_name"),
            "preset_id": gen_settings.get("preset_id"),
        }

        grid_item = ChatItem(
            chat_id=chat_id,
            item_type="generation_grid",
            grid_layout=json.dumps(grid_data)
        )
        session.add(grid_item)
        await session.flush()

        log.info(f"Created generation_grid ChatItem with id={grid_item.id}, job={job.id}")

        # Broadcast the grid item immediately
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": grid_item.to_dict()
        })

        return {
            "status": "queued",
            "success": True,
            "action_complete": True,
            "message": "Queued video generation. Request fulfilled - do not generate more unless user asks.",
        }
    except Exception as e:
        log.error(f"image_to_video failed with exception: {str(e)}", exc_info=True)
        return {
            "error": str(e),
            "success": False
        }


@tool(name="upscale_image",
      description="""Upscale an image to a higher resolution using AI.

Parameters:
- image_id: Media ID of the image to upscale (required)

The resolution/scale factor is configured in the tools panel settings.

Examples:
- upscale_image(image_id=123) - upscale using configured settings

Image upscales in the background - do not say upscaling is complete, only that it has started.""",
      injected_params=["chat_id", "session"])
async def upscale_image(
    chat_id: int,
    session: AsyncSession,
    image_id: int,
) -> dict:
    """
    Upscale an image to a higher resolution.

    Args:
        image_id: Media ID of the image to upscale.

    Returns: {
        "status": "started",
        "message": str,
        "success": bool
    }
    """
    try:
        # Handle image_id being passed as string
        if isinstance(image_id, str):
            image_id = int(image_id)

        log.info(f"upscale_image: image_id={image_id}")

        settings = get_settings()

        # Get chat
        result = await session.execute(select(Chat).where(Chat.id == chat_id))
        chat = result.scalar_one_or_none()

        if not chat:
            log.error(f"Chat {chat_id} not found in upscale_image")
            return {"error": "Chat not found", "success": False}

        # Resolve media ID to file path
        from database import MediaItem
        media_result = await session.execute(select(MediaItem).where(MediaItem.id == image_id))
        media = media_result.scalar_one_or_none()
        if not media:
            return {"error": f"Image (media ID {image_id}) not found", "success": False}
        input_image_path = media.file_path

        # Get the appropriate tool for upscale-image
        gen_settings = await get_generation_settings_for_task(session, chat, "upscale-image")
        if not gen_settings:
            log.error("No upscale-image tool configured")
            return {"error": "No upscale-image tool configured. Please configure a tool first.", "success": False}

        params = gen_settings["parameters"]
        log.info(f"upscale_image: gen_settings params = {params}")

        # Get output folder
        output_folder = gen_settings.get("output_folder")
        if not output_folder:
            generation_folders = settings.get_generation_folders_for_profile(get_current_profile())
            if not generation_folders:
                log.error("No generation folders configured")
                return {"error": "No generation folders configured", "success": False}
            output_folder = generation_folders[0].path

        # Get generator and model from settings
        generator_name = gen_settings.get("generator")
        model_name = gen_settings.get("model")

        # Find the configured generator
        generator = None
        if generator_name:
            generator = next((g for g in settings.generators if g.name == generator_name), None)

        # Fall back to first generator if not found
        if not generator:
            if not settings.generators:
                log.error("No generators configured")
                return {"error": "No generators configured", "success": False}
            generator = settings.generators[0]
            log.warning(f"Configured generator '{generator_name}' not found, using first: {generator.name}")

        # Model must come from tool
        if not model_name:
            log.error("No model configured in tool")
            return {"error": "No model configured in tool", "success": False}

        log.info(f"Using generator: {generator.type}/{generator.name}, model: {model_name}")

        # Generate seed
        seed = random.randint(0, 2**32 - 1)

        # Determine target resolution from settings
        # If scale_factor is set, compute from source image dimensions
        # Otherwise use the resolution setting (pixels mode)
        # NOTE: The workflow's "resolution" param is the TARGET SHORT EDGE
        scale_factor = params.get("scale_factor")
        if scale_factor:
            # Get source image dimensions - use the SHORT edge
            source_width = media.width or 1024
            source_height = media.height or 1024
            source_short_edge = min(source_width, source_height)
            target_resolution = int(source_short_edge * scale_factor)
            resolution_label = f"{scale_factor}x"
            log.info(f"Upscale using scale_factor={scale_factor}, source={source_width}x{source_height}, short_edge={source_short_edge}, target_short_edge={target_resolution}")
        else:
            target_resolution = params.get("resolution", 1080)
            resolution_label = f"{target_resolution}p"
            log.info(f"Upscale using fixed resolution (short edge)={target_resolution}")

        # Build parameters JSON for upscale
        parameters = {
            "input_images": [input_image_path],
            "input_media_ids": [image_id],  # Media IDs for lineage tracking
            "resolution": target_resolution,
            "color_correction": params.get("color_correction", "lab"),
            "seed": seed,
        }

        job = GenerationJob(
            status="queued",
            task_type="upscale-image",
            generator_type=generator.type,
            generator_name=generator.name,
            backend_name=generator.name,
            model_name=model_name,
            parameters=json.dumps(parameters),
            folder_path=output_folder,
            auto_delete_duration=gen_settings.get("auto_delete_duration", "1h"),
            generator_instance_id=f"chat-{chat_id}",
        )

        session.add(job)
        await session.flush()

        log.info(f"Created upscale-image job: {job.id}")
        await session.commit()

        # Create a generation_grid chat item
        # Upscale doesn't use prompts - just store the resolution label for display
        grid_data = {
            "job_ids": [job.id],
            "total_count": 1,
            "task_type": "upscale-image",
            "input_image_id": image_id,
            "resolution_label": resolution_label,  # e.g., "2x" or "1080p"

            "full_tool_id": gen_settings.get("full_tool_id"),
            "tool_name": gen_settings.get("tool_name"),
            "preset_id": gen_settings.get("preset_id"),
        }

        grid_item = ChatItem(
            chat_id=chat_id,
            item_type="generation_grid",
            grid_layout=json.dumps(grid_data)
        )
        session.add(grid_item)
        await session.flush()

        log.info(f"Created generation_grid ChatItem with id={grid_item.id}, job={job.id}")

        # Broadcast the grid item immediately
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": grid_item.to_dict()
        })

        return {
            "status": "queued",
            "success": True,
            "action_complete": True,
            "message": f"Queued image upscaling ({resolution_label}). Request fulfilled - do not upscale more unless user asks.",
        }
    except Exception as e:
        log.error(f"upscale_image failed with exception: {str(e)}", exc_info=True)
        return {
            "error": str(e),
            "success": False
        }


@tool(name="upscale_video",
      description="""Upscale a video to a higher resolution using AI.

Parameters:
- video_id: Media ID of the video to upscale (required)

The resolution is configured in the tools panel settings.

Examples:
- upscale_video(video_id=123) - upscale using configured settings

Video upscales in the background - do not say upscaling is complete, only that it has started.""",
      injected_params=["chat_id", "session"])
async def upscale_video(
    chat_id: int,
    session: AsyncSession,
    video_id: int,
) -> dict:
    """
    Upscale a video to a higher resolution.

    Args:
        video_id: Media ID of the video to upscale.

    Returns: {
        "status": "started",
        "message": str,
        "success": bool
    }
    """
    try:
        # Handle video_id being passed as string
        if isinstance(video_id, str):
            video_id = int(video_id)

        log.info(f"upscale_video: video_id={video_id}")

        settings = get_settings()

        # Get chat
        result = await session.execute(select(Chat).where(Chat.id == chat_id))
        chat = result.scalar_one_or_none()

        if not chat:
            log.error(f"Chat {chat_id} not found in upscale_video")
            return {"error": "Chat not found", "success": False}

        # Resolve media ID to file path
        from database import MediaItem
        media_result = await session.execute(select(MediaItem).where(MediaItem.id == video_id))
        media = media_result.scalar_one_or_none()
        if not media:
            return {"error": f"Video (media ID {video_id}) not found", "success": False}

        # Verify it's actually a video
        video_formats = ['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg']
        if media.file_format not in video_formats:
            return {"error": f"Media ID {video_id} is not a video (format: {media.file_format})", "success": False}

        input_video_path = media.file_path

        # Get the appropriate tool for upscale-video
        gen_settings = await get_generation_settings_for_task(session, chat, "upscale-video")
        if not gen_settings:
            log.error("No upscale-video tool configured")
            return {"error": "No upscale-video tool configured. Please configure a tool first.", "success": False}

        params = gen_settings["parameters"]
        log.info(f"upscale_video: gen_settings params = {params}")

        # Get output folder
        output_folder = gen_settings.get("output_folder")
        if not output_folder:
            generation_folders = settings.get_generation_folders_for_profile(get_current_profile())
            if not generation_folders:
                log.error("No generation folders configured")
                return {"error": "No generation folders configured", "success": False}
            output_folder = generation_folders[0].path

        # Get generator and model from settings
        generator_name = gen_settings.get("generator")
        model_name = gen_settings.get("model")

        # Find the configured generator
        generator = None
        if generator_name:
            generator = next((g for g in settings.generators if g.name == generator_name), None)

        # Fall back to first generator if not found
        if not generator:
            if not settings.generators:
                log.error("No generators configured")
                return {"error": "No generators configured", "success": False}
            generator = settings.generators[0]
            log.warning(f"Configured generator '{generator_name}' not found, using first: {generator.name}")

        # Model must come from tool
        if not model_name:
            log.error("No model configured in tool")
            return {"error": "No model configured in tool", "success": False}

        log.info(f"Using generator: {generator.type}/{generator.name}, model: {model_name}")

        # Generate seed
        seed = random.randint(0, 2**32 - 1)

        # Determine target resolution from settings
        # If scale_factor is set, compute from source video dimensions
        # Otherwise use the resolution setting (pixels mode)
        # NOTE: The workflow's "resolution" param is the TARGET SHORT EDGE
        scale_factor = params.get("scale_factor")
        if scale_factor:
            # Get source video dimensions - use the SHORT edge
            source_width = media.width or 854
            source_height = media.height or 480
            source_short_edge = min(source_width, source_height)
            target_resolution = int(source_short_edge * scale_factor)
            resolution_label = f"{scale_factor}x"
            log.info(f"Upscale using scale_factor={scale_factor}, source={source_width}x{source_height}, short_edge={source_short_edge}, target_short_edge={target_resolution}")
        else:
            target_resolution = params.get("resolution", 1080)
            resolution_label = f"{target_resolution}p"
            log.info(f"Upscale using fixed resolution (short edge)={target_resolution}")

        # Build parameters JSON for upscale
        parameters = {
            "input_video": input_video_path,
            "input_media_id": video_id,  # Media ID for lineage tracking
            "resolution": target_resolution,
            "color_correction": params.get("color_correction", "lab"),
            "seed": seed,
        }

        job = GenerationJob(
            status="queued",
            task_type="upscale-video",
            generator_type=generator.type,
            generator_name=generator.name,
            backend_name=generator.name,
            model_name=model_name,
            parameters=json.dumps(parameters),
            folder_path=output_folder,
            auto_delete_duration=gen_settings.get("auto_delete_duration", "1h"),
            generator_instance_id=f"chat-{chat_id}",
        )

        session.add(job)
        await session.flush()

        log.info(f"Created upscale-video job: {job.id}")
        await session.commit()

        # Create a generation_grid chat item
        # Upscale doesn't use prompts - just store the resolution label for display
        grid_data = {
            "job_ids": [job.id],
            "total_count": 1,
            "task_type": "upscale-video",
            "input_video_id": video_id,
            "resolution_label": resolution_label,  # e.g., "2x" or "1080p"

            "full_tool_id": gen_settings.get("full_tool_id"),
            "tool_name": gen_settings.get("tool_name"),
            "preset_id": gen_settings.get("preset_id"),
        }

        grid_item = ChatItem(
            chat_id=chat_id,
            item_type="generation_grid",
            grid_layout=json.dumps(grid_data)
        )
        session.add(grid_item)
        await session.flush()

        log.info(f"Created generation_grid ChatItem with id={grid_item.id}, job={job.id}")

        # Broadcast the grid item immediately
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": grid_item.to_dict()
        })

        return {
            "status": "queued",
            "success": True,
            "action_complete": True,
            "message": f"Queued video upscaling ({resolution_label}). Request fulfilled - do not upscale more unless user asks.",
        }
    except Exception as e:
        log.error(f"upscale_video failed with exception: {str(e)}", exc_info=True)
        return {
            "error": str(e),
            "success": False
        }


@tool(name="get_image_info",
      description="""Get detailed information about a specific image by its media ID.

Returns comprehensive metadata including:
- File info (path, format, size, dimensions)
- AI-generated caption and extracted prompt
- Keywords
- Tags, boards, and markers
- Generation metadata (if AI-generated)
- Dates (created, indexed)

Use this when you need to know details about a specific image.""",
      injected_params=["session"])
async def get_image_info(
    session: AsyncSession,
    media_id: int,
) -> dict:
    """
    Get detailed information about an image.

    Args:
        media_id: The ID of the image to get info for.

    Returns: {
        "media_id": int,
        "file_path": str,
        "file_format": str,
        "file_size": int,
        "width": int,
        "height": int,
        "megapixels": float,
        "duration": float (for videos),
        "caption": str,
        "prompt": str,
        "keywords": str,
        "tags": [{"id": int, "name": str}, ...],
        "boards": [{"id": int, "name": str}, ...],
        "markers": [{"id": int, "name": str, "color": str}, ...],
        "generation_metadata": dict (if AI-generated),
        "created_date": str,
        "indexed_date": str,
        "success": bool
    }
    """
    try:
        from database import Board, BoardItem, BoardSection, MediaItem, Tag, MediaTag, Marker, MediaMarker

        result = await session.execute(
            select(MediaItem).where(MediaItem.id == media_id)
        )
        media = result.scalar_one_or_none()

        if not media:
            return {"error": f"Image with ID {media_id} not found", "success": False}

        # Parse generation metadata if present
        gen_metadata = None
        if media.generation_metadata:
            try:
                gen_metadata = json.loads(media.generation_metadata)
            except json.JSONDecodeError:
                gen_metadata = media.generation_metadata

        # Get tags for this image
        tags_result = await session.execute(
            select(Tag).join(MediaTag, Tag.id == MediaTag.tag_id).where(MediaTag.media_id == media_id)
        )
        tags = [{"id": tag.id, "name": tag.tag_text} for tag in tags_result.scalars().all()]

        # Get boards for this image
        boards_result = await session.execute(
            select(Board)
            .join(BoardSection, and_(BoardSection.board_id == Board.id, BoardSection.deleted_at.is_(None)))
            .join(BoardItem, BoardItem.board_section_id == BoardSection.id)
            .where(BoardItem.media_id == media_id)
            .where(Board.deleted_at.is_(None))
        )
        boards = [{"id": board.id, "name": board.name} for board in boards_result.scalars().all()]

        # Get markers for this image
        markers_result = await session.execute(
            select(MediaMarker).where(MediaMarker.media_id == media_id)
        )
        markers = [{"id": mm.marker.id, "name": mm.marker.name, "color": mm.marker.color} for mm in markers_result.scalars().all()]

        info = {
            "media_id": media.id,
            "file_path": media.file_path,
            "file_format": media.file_format,
            "file_size": media.file_size,
            "width": media.width,
            "height": media.height,
            "megapixels": media.megapixels,
            "duration": media.duration,
            "prompt": media.extracted_prompt,
            "keywords": media.keywords,
            "tags": tags,
            "boards": boards,
            "markers": markers,
            "generation_metadata": gen_metadata,
            "created_date": media.created_date.isoformat() if media.created_date else None,
            "indexed_date": media.indexed_date.isoformat() if media.indexed_date else None,
            "is_generated": gen_metadata is not None,
            "is_video": media.file_format in ['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg'],
            "success": True
        }

        return info
    except Exception as e:
        log.error(f"get_image_info failed: {str(e)}", exc_info=True)
        return {"error": str(e), "success": False}


@tool(name="show_images",
      description="""Display one or more images to the user by their media IDs.

Use this to show specific images in the chat. The images will be displayed as thumbnails that the user can click to view in full size.

Examples:
- show_images(media_ids=[123]) - show a single image
- show_images(media_ids=[123, 456, 789]) - show multiple images""",
      injected_params=["chat_id", "session"])
async def show_images(
    chat_id: int,
    session: AsyncSession,
    media_ids: list,
) -> dict:
    """
    Display images to the user.

    Args:
        media_ids: List of media IDs to display.

    Returns: {
        "displayed": int,
        "success": bool
    }
    """
    try:
        from database import MediaItem, ChatItem

        if not media_ids:
            return {"displayed": 0, "success": True, "message": "No images to display"}

        # Handle JSON string input - be robust to LLM formatting issues
        if isinstance(media_ids, str):
            try:
                media_ids = json.loads(media_ids)
            except json.JSONDecodeError as e:
                # Try to extract numbers from malformed input like "[1][2][3]" or "1, 2, 3"
                import re
                numbers = re.findall(r'\d+', media_ids)
                if numbers:
                    media_ids = [int(n) for n in numbers]
                else:
                    return {"error": f"Invalid media_ids format: {e}", "success": False}

        # Ensure it's a list
        if not isinstance(media_ids, list):
            media_ids = [media_ids]

        # Convert all elements to integers
        try:
            media_ids = [int(mid) for mid in media_ids]
        except (ValueError, TypeError) as e:
            return {"error": f"Invalid media ID values: {e}", "success": False}

        # Validate media IDs exist and aren't trashed
        result = await session.execute(
            select(MediaItem).where(
                MediaItem.id.in_(media_ids),
                MediaItem.deleted_at.is_(None),
            )
        )
        found_items = result.scalars().all()
        found_ids = {item.id for item in found_items}

        # Build list of valid images with basic info
        images = []
        for media_id in media_ids:
            if media_id in found_ids:
                item = next(i for i in found_items if i.id == media_id)
                images.append({
                    "media_id": item.id,
                    "width": item.width,
                    "height": item.height,
                    "file_format": item.file_format,
                    "prompt": (item.extracted_prompt or "")[:100],
                })

        if not images:
            return {"error": "No valid images found for the provided IDs", "success": False}

        # Create an image_display chat item
        display_data = {
            "images": images,
            "count": len(images)
        }

        display_item = ChatItem(
            chat_id=chat_id,
            item_type="image_display",
            item_metadata=json.dumps(display_data)
        )
        session.add(display_item)
        await session.flush()

        # Broadcast the display item
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": display_item.to_dict()
        })

        return {
            "displayed": len(images),
            "success": True
        }
    except Exception as e:
        log.error(f"show_images failed: {str(e)}", exc_info=True)
        return {"error": str(e), "success": False}


@tool(name="list_images",
      description="""List images available in this chat that can be used for editing or video generation.

Returns the most recent images with their media IDs, prompts, and generation info.
Use this to find media IDs needed for edit_image or image_to_video tools.

No parameters required - just call list_images() to see available images.""",
      injected_params=["chat_id", "session"])
async def list_images(
    chat_id: int,
    session: AsyncSession,
) -> dict:
    """
    List images available in this chat.

    Returns: {
        "images": [
            {"media_id": int, "prompt": str, "created_at": str, ...},
            ...
        ],
        "count": int,
        "success": bool
    }
    """
    try:
        from database import MediaItem

        # Find all generation_grid items for this chat
        result = await session.execute(
            select(ChatItem)
            .where(ChatItem.chat_id == chat_id)
            .where(ChatItem.item_type == "generation_grid")
            .order_by(ChatItem.created_at.desc())
            .limit(10)  # Last 10 grids
        )
        grid_items = result.scalars().all()

        images = []
        seen_media_ids = set()

        for grid_item in grid_items:
            try:
                grid_data = json.loads(grid_item.grid_layout) if grid_item.grid_layout else {}
            except json.JSONDecodeError:
                continue

            job_ids = grid_data.get("job_ids", [])

            # Get job details and media IDs
            for job_id in job_ids:
                job_result = await session.execute(
                    select(GenerationJob).where(GenerationJob.id == job_id)
                )
                job = job_result.scalar_one_or_none()

                if not job or not job.result_media_id:
                    continue

                if job.result_media_id in seen_media_ids:
                    continue
                seen_media_ids.add(job.result_media_id)

                # Get media details
                media_result = await session.execute(
                    select(MediaItem).where(MediaItem.id == job.result_media_id)
                )
                media = media_result.scalar_one_or_none()

                if not media or media.deleted_at:
                    continue

                # Parse job parameters for prompt
                try:
                    params = json.loads(job.parameters) if job.parameters else {}
                except json.JSONDecodeError:
                    params = {}

                images.append({
                    "media_id": media.id,
                    "prompt": params.get("prompt", "")[:100],  # Truncate long prompts
                    "created_at": media.created_date.isoformat() if media.created_date else None,
                    "width": media.width,
                    "height": media.height,
                    "task_type": job.task_type or "text-to-image",
                })

                # Limit to 20 images
                if len(images) >= 20:
                    break

            if len(images) >= 20:
                break

        return {
            "images": images,
            "count": len(images),
            "success": True
        }
    except Exception as e:
        log.error(f"list_images failed: {str(e)}", exc_info=True)
        return {
            "error": str(e),
            "success": False
        }


@tool(name="search_images",
      description="""Search for images using natural language. Uses CLIP AI to find visually similar images based on your text description.

Examples:
- search_images(query="a golden retriever playing in the park")
- search_images(query="sunset over mountains", limit=10)
- search_images(query="portrait of a woman with red hair")

Returns the top matching images with their media IDs, prompts, and similarity scores.
Results are displayed in-chat. Use the browser_url in the response to see more results in the full browser.""",
      injected_params=["chat_id", "session"])
async def search_images(
    chat_id: int,
    session: AsyncSession,
    query: str,
    limit: int = 5,
) -> dict:
    """
    Search for images using CLIP text-to-image similarity.

    Args:
        query: Natural language description of the images to find.
        limit: Maximum number of results to return (default 5, max 20).

    Returns: {
        "results": [{"media_id": int, "similarity": float, "prompt": str, ...}, ...],
        "count": int,
        "browser_url": str,
        "success": bool
    }
    """
    try:
        from database import MediaItem
        from clip_service import get_clip_service
        from config import get_settings
        import base64

        if not query or not str(query).strip():
            return {"error": "No search query provided", "success": False}

        query = str(query).strip()
        limit = min(max(1, limit), 20)  # Clamp to 1-20

        log.info(f"search_images: query='{query[:50]}...', limit={limit}")

        settings = get_settings()
        clip_service = get_clip_service()

        # Encode the search query using CLIP
        query_embedding = clip_service.encode_text(query)

        # Get all media items with embeddings
        result = await session.execute(
            select(MediaItem)
            .where(MediaItem.clip_embedding.isnot(None))
            .where(MediaItem.deleted_at.is_(None))
            .where(MediaItem.metadata_status == 'completed')
        )
        all_items = result.scalars().all()

        # Compute similarities
        from clip_service import CLIP_EMBEDDING_DIM
        threshold = settings.clip_text_similarity_threshold
        scored_items = []

        for item in all_items:
            embedding = item.get_embedding()
            if embedding is not None:
                # Skip items with stale embeddings (wrong dimensions)
                if embedding.shape[0] != CLIP_EMBEDDING_DIM:
                    continue
                similarity = clip_service.compute_similarity(query_embedding, embedding)
                if similarity >= threshold:
                    scored_items.append({
                        "media_id": item.id,
                        "similarity": float(similarity),
                        "prompt": (item.extracted_prompt or "")[:100],
                        "width": item.width,
                        "height": item.height,
                        "file_format": item.file_format,
                    })

        # Sort by similarity and take top N
        scored_items.sort(key=lambda x: x["similarity"], reverse=True)
        results = scored_items[:limit]

        # Build browser URL with the search query
        # Use compact URL params: stt=similarToText, s=sim (sort by similarity)
        from urllib.parse import quote
        browser_url = f"/?stt={quote(query)}&s=sim"

        # Create a search_results chat item to display the results
        if results:
            search_data = {
                "query": query,
                "results": results,
                "total_matches": len(scored_items),
                "browser_url": browser_url
            }

            search_item = ChatItem(
                chat_id=chat_id,
                item_type="search_results",
                item_metadata=json.dumps(search_data)
            )
            session.add(search_item)
            await session.flush()

            # Broadcast the search results item
            await ws_manager.broadcast("chat_item_created", {
                "chat_id": chat_id,
                "item": search_item.to_dict()
            })

        return {
            "results": results,
            "count": len(results),
            "total_matches": len(scored_items),
            "browser_url": browser_url,
            "success": True
        }
    except Exception as e:
        log.error(f"search_images failed: {str(e)}", exc_info=True)
        return {"error": str(e), "success": False}


@tool(name="get_filter_options",
      description="""Get available filter options for browsing images. Use this to discover what filters are available before building a filtered query.

Parameters:
- filter_type: Which filter options to get. Options: "keywords", "folders", "markers", "all"

Returns available values for the requested filter type(s) with counts of how many images have each value.""",
      injected_params=["session"])
async def get_filter_options(
    session: AsyncSession,
    filter_type: str = "all",
) -> dict:
    """
    Get available filter options for image browsing.

    Args:
        filter_type: Type of filter options to retrieve ("keywords", "folders", "markers", "all")

    Returns: {
        "keywords": [{"keyword": str, "count": int}, ...],
        "folders": [{"path": str, "count": int}, ...],
        "markers": [{"id": int, "name": str, "color": str, "count": int}, ...],
        "success": bool
    }
    """
    try:
        from database import MediaItem, Keyword, MediaKeyword, Marker, MediaMarker
        from config import get_settings
        from sqlalchemy import func

        result_data = {"success": True}
        filter_type = filter_type.lower().strip()

        # Get keywords
        if filter_type in ("keywords", "all"):
            keyword_query = select(
                Keyword.keyword_text,
                func.count(func.distinct(MediaKeyword.media_id)).label('count')
            ).select_from(Keyword).join(
                MediaKeyword, Keyword.id == MediaKeyword.keyword_id
            ).join(
                MediaItem, MediaKeyword.media_id == MediaItem.id
            ).where(
                MediaItem.deleted_at.is_(None)
            ).group_by(
                Keyword.keyword_text
            ).order_by(
                func.count(func.distinct(MediaKeyword.media_id)).desc()
            ).limit(50)

            result = await session.execute(keyword_query)
            keywords = [{"keyword": kw, "count": count} for kw, count in result.all()]
            result_data["keywords"] = keywords

        # Get folders
        if filter_type in ("folders", "all"):
            settings = get_settings()
            # Get folder paths from config
            folders = []
            for folder in settings.folders:
                # Count items in this folder - ensure path ends with / to avoid partial matches
                folder_path = folder.path.rstrip('/') + '/'
                count_result = await session.execute(
                    select(func.count(MediaItem.id))
                    .where(MediaItem.file_path.like(f"{folder_path}%"))
                    .where(MediaItem.deleted_at.is_(None))
                )
                count = count_result.scalar() or 0
                folders.append({
                    "path": folder.path,
                    "count": count,
                    "readonly": folder.readonly,
                    "allow_generate": folder.allow_generate
                })
            result_data["folders"] = folders

        # Get markers
        if filter_type in ("markers", "all"):
            marker_query = select(
                Marker,
                func.count(func.distinct(MediaMarker.media_id)).label('count')
            ).outerjoin(
                MediaMarker, Marker.id == MediaMarker.marker_id
            ).group_by(
                Marker.id
            ).order_by(
                func.count(func.distinct(MediaMarker.media_id)).desc()
            )

            result = await session.execute(marker_query)
            markers = []
            for marker, count in result.all():
                markers.append({
                    "id": marker.id,
                    "name": marker.name,
                    "color": marker.color,
                    "count": count or 0
                })
            result_data["markers"] = markers

        return result_data
    except Exception as e:
        log.error(f"get_filter_options failed: {str(e)}", exc_info=True)
        return {"error": str(e), "success": False}


@tool(name="browse_with_filters",
      description="""Browse the image library with specific filters. Returns top results and a URL to view in the full browser.

Use this after get_filter_options to build a filtered query. All filter parameters are optional - only include the ones you want to use.

Filter parameters:
- keywords: List of keywords to filter by (AND logic - images must have ALL keywords)
- folders: List of folder paths to include
- markers: List of marker IDs to filter by (OR logic - images have any marker)
- caption_query: Search within image captions
- prompt_query: Search within image prompts/metadata
- media_types: List of media types ("images", "videos")
- resolutions: List of resolutions ("small", "medium", "large", "huge")
- is_generated: Filter for AI-generated images (true/false)

Returns top 5 matching images and a browser URL for the full filtered view.""",
      injected_params=["chat_id", "session"])
async def browse_with_filters(
    chat_id: int,
    session: AsyncSession,
    keywords: list = None,
    folders: list = None,
    markers: list = None,
    caption_query: str = None,
    prompt_query: str = None,
    media_types: list = None,
    resolutions: list = None,
    is_generated: bool = None,
) -> dict:
    """
    Browse images with filters and get a browser URL.

    Returns: {
        "results": [{"media_id": int, "prompt": str, ...}, ...],
        "count": int,
        "total_matches": int,
        "browser_url": str,
        "success": bool
    }
    """
    try:
        from database import MediaItem, ChatItem, MediaKeyword, Keyword, MediaMarker
        import base64
        from urllib.parse import urlencode

        log.info(f"browse_with_filters: keywords={keywords}, folders={folders}, markers={markers}")

        # Build the query
        query = select(MediaItem).where(
            MediaItem.deleted_at.is_(None),
            MediaItem.metadata_status == 'completed'
        )

        # Helper to safely parse JSON list parameters from LLM
        def safe_parse_list(value, default_single=True):
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                if value.startswith('['):
                    try:
                        return json.loads(value)
                    except json.JSONDecodeError:
                        # Malformed JSON, treat as single value
                        return [value] if default_single else []
                return [value] if default_single else []
            return [value] if value and default_single else []

        # Apply keyword filters (AND logic)
        if keywords:
            keywords = safe_parse_list(keywords)
            for kw in keywords:
                query = query.where(MediaItem.keywords.ilike(f"%{kw}%"))

        # Apply folder filters (OR logic) - ensure paths end with / to avoid partial matches
        if folders:
            folders = safe_parse_list(folders)
            from sqlalchemy import or_
            folder_conditions = [MediaItem.file_path.like(f"{f.rstrip('/') + '/'}%") for f in folders]
            if folder_conditions:
                query = query.where(or_(*folder_conditions))

        # Apply marker filters (OR logic)
        if markers:
            markers = safe_parse_list(markers)
            try:
                markers = [int(m) for m in markers]
            except (ValueError, TypeError):
                markers = []
            # Subquery to get media IDs with any of the specified markers
            marker_subquery = select(MediaMarker.media_id).where(
                MediaMarker.marker_id.in_(markers)
            ).distinct()
            query = query.where(MediaItem.id.in_(marker_subquery))

        # Apply caption query
        if caption_query:
            query = query.where(MediaItem.vlm_caption.ilike(f"%{caption_query}%"))

        # Apply prompt query
        if prompt_query:
            query = query.where(MediaItem.extracted_prompt.ilike(f"%{prompt_query}%"))

        # Apply media type filter
        video_formats = ['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg']
        image_formats = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']

        if media_types:
            media_types = safe_parse_list(media_types)
            from sqlalchemy import or_
            format_conditions = []
            for mt in media_types:
                if mt == 'images':
                    format_conditions.append(MediaItem.file_format.in_(image_formats))
                elif mt == 'videos':
                    format_conditions.append(MediaItem.file_format.in_(video_formats))
            if format_conditions:
                query = query.where(or_(*format_conditions))

        # Apply resolution filter
        if resolutions:
            resolutions = safe_parse_list(resolutions)
            from sqlalchemy import or_
            res_conditions = []
            for res in resolutions:
                if res == 'small':
                    res_conditions.append(MediaItem.megapixels < 0.8)
                elif res == 'medium':
                    res_conditions.append((MediaItem.megapixels >= 0.8) & (MediaItem.megapixels < 1.5))
                elif res == 'large':
                    res_conditions.append((MediaItem.megapixels >= 1.5) & (MediaItem.megapixels < 3.0))
                elif res == 'huge':
                    res_conditions.append(MediaItem.megapixels >= 3.0)
            if res_conditions:
                query = query.where(or_(*res_conditions))

        # Apply is_generated filter
        if is_generated is not None:
            if is_generated:
                query = query.where(MediaItem.generation_metadata.isnot(None))
            else:
                query = query.where(MediaItem.generation_metadata.is_(None))

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await session.execute(count_query)
        total_matches = total_result.scalar() or 0

        # Get top 5 results ordered by created_date desc
        query = query.order_by(MediaItem.created_date.desc()).limit(5)
        result = await session.execute(query)
        items = result.scalars().all()

        results = []
        for item in items:
            results.append({
                "media_id": item.id,
                "prompt": (item.extracted_prompt or "")[:100],
                "width": item.width,
                "height": item.height,
                "file_format": item.file_format,
                "keywords": item.keywords[:200] if item.keywords else None,
            })

        # Build browser URL with compact encoding (matching frontend useUrlState.js)
        from urllib.parse import quote
        url_params = []

        if caption_query:
            url_params.append(f"cq={quote(caption_query)}")
        if prompt_query:
            url_params.append(f"pq={quote(prompt_query)}")
        if keywords:
            url_params.append(f"k={quote(','.join(keywords))}")
        if folders:
            # Base64 encode folders (matching frontend)
            url_params.append(f"f={base64.b64encode('|'.join(folders).encode()).decode()}")
        if media_types:
            compact = ','.join('i' if t == 'images' else 'v' for t in media_types)
            url_params.append(f"mt={compact}")
        if resolutions:
            compact = ','.join(r[0] for r in resolutions)  # s, m, l, h
            url_params.append(f"r={compact}")
        # Note: markers and is_generated don't have URL support in frontend yet

        browser_url = "/?" + "&".join(url_params) if url_params else "/"

        # Create a search_results chat item to display the results
        if results:
            search_data = {
                "filter_description": _build_filter_description(keywords, folders, markers, caption_query, prompt_query, media_types, resolutions, is_generated),
                "results": results,
                "total_matches": total_matches,
                "browser_url": browser_url
            }

            search_item = ChatItem(
                chat_id=chat_id,
                item_type="search_results",
                item_metadata=json.dumps(search_data)
            )
            session.add(search_item)
            await session.flush()

            # Broadcast the search results item
            await ws_manager.broadcast("chat_item_created", {
                "chat_id": chat_id,
                "item": search_item.to_dict()
            })

        return {
            "results": results,
            "count": len(results),
            "total_matches": total_matches,
            "browser_url": browser_url,
            "success": True
        }
    except Exception as e:
        log.error(f"browse_with_filters failed: {str(e)}", exc_info=True)
        return {"error": str(e), "success": False}


def _build_filter_description(keywords, folders, markers, caption_query, prompt_query, media_types, resolutions, is_generated):
    """Build a human-readable description of the active filters."""
    parts = []
    if keywords:
        parts.append(f"keywords: {', '.join(keywords)}")
    if folders:
        parts.append(f"folders: {len(folders)} selected")
    if markers:
        parts.append(f"markers: {len(markers)} selected")
    if caption_query:
        parts.append(f"caption contains: '{caption_query}'")
    if prompt_query:
        parts.append(f"prompt contains: '{prompt_query}'")
    if media_types:
        parts.append(f"types: {', '.join(media_types)}")
    if resolutions:
        parts.append(f"resolutions: {', '.join(resolutions)}")
    if is_generated is not None:
        parts.append("AI-generated" if is_generated else "non-generated")
    return "; ".join(parts) if parts else "all images"
