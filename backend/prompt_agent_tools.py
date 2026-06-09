"""Tool schemas for the prompt-editor mini-agent.

These are the OpenAI function-calling schemas advertised to the LLM by the
`/api/prompt/agent/step` endpoint. The frontend `commandSurface` (ToolView.vue)
must expose a handler under each tool's exact `name` — the agent operates the
frontend with parity to the user, so every tool maps to the same handler a click
triggers.

Tiers (see docs/plan): A–G = Tier 1 (content edits, undoable), H = Tier 2
(actions with side effects). Tier 3 (model switch / presets / tool hop) is
deliberately NOT advertised here yet.
"""
from typing import Any, Dict, List


def _fn(name: str, description: str, properties: Dict[str, Any], required: List[str] | None = None) -> Dict[str, Any]:
    """Build one OpenAI-format function-tool schema."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


# --- A. Prompt text ---------------------------------------------------------
_PROMPT_TOOLS = [
    _fn(
        "set_prompt",
        "Replace the ENTIRE prompt text. Use for big rewrites or starting over. "
        "Preserve [bracketed] verbatim segments and {a|b|c} wildcards unless asked to change them. "
        "An empty string clears the prompt.",
        {"text": {"type": "string"}},
        ["text"],
    ),
    _fn(
        "edit_prompt",
        "Surgically edit the prompt by exact string replacement — cheaper and faster than "
        "rewriting the whole thing. old_string must match the current prompt exactly (including "
        "whitespace). Replaces the first occurrence unless replace_all is true.",
        {
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean", "description": "Replace all occurrences. Default false."},
        },
        ["old_string", "new_string"],
    ),
    _fn("clear_prompt", "Empty the prompt text.", {}),
]

# --- B. Parameters (fully data-defined) -------------------------------------
_PARAM_TOOLS = [
    _fn(
        "set_parameter",
        "Set any generation parameter that appears in state_context.parameter_schema. This covers "
        "negative_prompt, width, height, megapixels, aspect_ratio, guidance, cfg, steps, denoise, "
        "sampler, scheduler, and any other parameter the current tool/model exposes. The value must "
        "respect that parameter's type and its range/enum from parameter_schema.",
        {
            "name": {"type": "string", "description": "A key present in state_context.parameter_schema."},
            "value": {
                "type": "string",
                "description": "The value as a string. Numbers are parsed (e.g. \"2.0\"); for "
                               "enum params pass the exact option text; booleans as \"true\"/\"false\".",
            },
        },
        ["name", "value"],
    ),
    _fn(
        "set_seed",
        "Set the seed to a specific integer. This also turns OFF randomize-seed. To randomize "
        "instead, use set_randomize_seed.",
        {"value": {"type": "integer", "description": "The seed value."}},
        ["value"],
    ),
    _fn(
        "set_randomize_seed",
        "Turn randomize-seed on or off.",
        {"enabled": {"type": "boolean"}},
        ["enabled"],
    ),
    _fn(
        "set_batch_size",
        "Set the batch size — how many images one click of Run queues (same as the Run "
        "button's batch dropdown). 1 means a single generation. Each image is queued "
        "separately with its own seed, exactly like pressing Run that many times.",
        {"size": {"type": "integer", "description": "Images per run, 1-8.", "minimum": 1, "maximum": 8}},
        ["size"],
    ),
    _fn(
        "set_resolution",
        "Set the output image size. Resolution is a dedicated control and is NOT a key in "
        "parameter_schema — use THIS tool for anything about image size, aspect ratio, or "
        "megapixels. Provide whatever the user expressed: width+height in pixels, and/or "
        "megapixels, and/or aspect_ratio (e.g. '1:1', '16:9'), and/or image_size. For upscalers "
        "(state_context.resolution.mode == 'upscale') use scale_factor (e.g. 2 for 2×) or "
        "target_resolution (short edge in px) instead. The tool's current mode and allowed values "
        "are in state_context.resolution; your values are converted/snapped to what this tool "
        "actually supports.",
        {
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "megapixels": {"type": "number"},
            "aspect_ratio": {"type": "string", "description": "e.g. '1:1', '16:9'"},
            "image_size": {"type": "string", "description": "e.g. '1K', '2K' — only tools that use it"},
            "scale_factor": {"type": "number", "description": "Upscalers only: relative scale, e.g. 2 for 2× (range 0.5–4)."},
            "target_resolution": {"type": "integer", "description": "Upscalers only: target short-edge size in px (480–4320)."},
        },
    ),
]

# --- C. Suggestion categories ----------------------------------------------
_CATEGORY_TOOLS = [
    _fn(
        "add_category",
        "Add a suggestion category (a pill with a dropdown of options) below the prompt.",
        {
            "label": {"type": "string", "description": "Display name, e.g. 'Age'."},
            "key": {"type": "string", "description": "Optional machine key; derived from label if omitted."},
            "allow_wildcard": {"type": "boolean", "description": "Default false."},
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional initial options; generated from the prompt if omitted.",
            },
        },
        ["label"],
    ),
    _fn("remove_category", "Remove a suggestion category by its key.", {"key": {"type": "string"}}, ["key"]),
    _fn(
        "set_category_options",
        "Replace a category's option list. Use for requests like 'only dark hair colors'.",
        {
            "key": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
        },
        ["key", "options"],
    ),
    _fn(
        "refresh_category",
        "Regenerate fresh options for one category from the current prompt.",
        {"key": {"type": "string"}},
        ["key"],
    ),
    _fn("refresh_ideas", "Re-run the full suggestion fetch (all categories) for the current prompt.", {}),
]

# --- D. Reference images ----------------------------------------------------
_IMAGE_TOOLS = [
    _fn(
        "flip_image",
        "Flip a reference image horizontally or vertically.",
        {"index": {"type": "integer", "description": "0-based image index."},
         "axis": {"type": "string", "enum": ["horizontal", "vertical"]}},
        ["index", "axis"],
    ),
    _fn(
        "rotate_image",
        "Rotate a reference image 90° left or right.",
        {"index": {"type": "integer"}, "direction": {"type": "string", "enum": ["left", "right"]}},
        ["index", "direction"],
    ),
    _fn(
        "reset_image_transforms",
        "Clear flip/rotate/scale/extend/preprocess on one reference image, back to the original.",
        {"index": {"type": "integer"}},
        ["index"],
    ),
    _fn("remove_image", "Remove one reference image.", {"index": {"type": "integer"}}, ["index"]),
    _fn("clear_images", "Remove all reference images.", {}),
    _fn(
        "reorder_image",
        "Move a reference image from one position to another.",
        {"from_index": {"type": "integer"}, "to_index": {"type": "integer"}},
        ["from_index", "to_index"],
    ),
    _fn(
        "preprocess_image",
        "Apply (or clear) a ControlNet preprocessor on a reference image. Use 'none' to clear.",
        {
            "index": {"type": "integer"},
            "preprocessor": {
                "type": "string",
                "enum": ["canny", "depth", "lineart", "lineart_realistic", "pose", "pose_hands", "none"],
            },
        },
        ["index", "preprocessor"],
    ),
    _fn(
        "scale_image",
        "Scale a reference image by factor, target megapixels, or manual width/height.",
        {
            "index": {"type": "integer"},
            "mode": {"type": "string", "enum": ["factor", "megapixels", "manual"]},
            "factor": {"type": "number"},
            "megapixels": {"type": "number"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
        },
        ["index", "mode"],
    ),
    _fn(
        "extend_image",
        "Extend the canvas (outpaint padding) around a reference image. Padding values are percentages.",
        {
            "index": {"type": "integer"},
            "top": {"type": "number"}, "bottom": {"type": "number"},
            "left": {"type": "number"}, "right": {"type": "number"},
            "bg_color": {"type": "string", "description": "hex, e.g. #ffffff"},
        },
        ["index"],
    ),
]

# --- E. LoRAs ---------------------------------------------------------------
_LORA_TOOLS = [
    _fn(
        "search_loras",
        "Find available LoRAs by colloquial name or keywords. There may be thousands of LoRAs and "
        "they are NOT all listed in state_context, so use this to resolve what the user means before "
        "setting weight/enabled. Returns matching { name, path }.",
        {"query": {"type": "string"}},
        ["query"],
    ),
    _fn(
        "set_lora_weight",
        "Set a LoRA's weight, identified by name or path (from search_loras or state_context.loras). "
        "Adds the LoRA if it is not already applied.",
        {"lora": {"type": "string", "description": "name or path"}, "weight": {"type": "number"}},
        ["lora", "weight"],
    ),
    _fn(
        "set_lora_enabled",
        "Enable or disable a LoRA by name or path. Enabling adds it if not present; disabling keeps "
        "the row but turns it off.",
        {"lora": {"type": "string"}, "enabled": {"type": "boolean"}},
        ["lora", "enabled"],
    ),
]

# --- E2. Post-processing chain ------------------------------------------------
# A linear list of media→media steps that auto-runs after each generation
# ("after you generate, always upscale 2× and fix the face"). Current steps and
# the built-in filter ids are in state_context.post_processing; steps are
# addressed by id, 1-based position, or name.
_CHAIN_TOOLS = [
    _fn(
        "set_postprocessing_enabled",
        "Turn the post-processing chain on or off (the panel's header toggle). When on, the "
        "enabled steps run automatically after every generation.",
        {"enabled": {"type": "boolean"}},
        ["enabled"],
    ),
    _fn(
        "add_chain_step",
        "Append (or insert) a step in the post-processing chain. kind 'filter' = a built-in "
        "filter from state_context.post_processing.available_filters; kind 'tool' = an STP "
        "image→image tool resolved by name (e.g. 'upscale', 'face restore'). Steps ship with "
        "sensible defaults — pass settings only for explicit requests.",
        {
            "kind": {"type": "string", "enum": ["tool", "filter"]},
            "ref": {"type": "string", "description": "Filter id, or STP tool name/id."},
            "position": {"type": "integer", "description": "1-based insert position; appends if omitted."},
            "settings": {"type": "object", "description": "Initial setting overrides."},
        },
        ["kind", "ref"],
    ),
    _fn(
        "remove_chain_step",
        "Remove a step from the chain. To keep it but stop it running, use "
        "set_chain_step_enabled instead.",
        {"step": {"type": "string", "description": "Step id, 1-based position, or name."}},
        ["step"],
    ),
    _fn(
        "reorder_chain_step",
        "Move a chain step to a new position.",
        {
            "step": {"type": "string", "description": "Step id, 1-based position, or name."},
            "to_position": {"type": "integer", "description": "1-based target position."},
        },
        ["step", "to_position"],
    ),
    _fn(
        "configure_chain_step",
        "Update a chain step's settings (merged into its current settings). Filter params are in "
        "state_context.post_processing.available_filters; tool steps accept that tool's schema params.",
        {
            "step": {"type": "string", "description": "Step id, 1-based position, or name."},
            "settings": {"type": "object"},
        },
        ["step", "settings"],
    ),
    _fn(
        "set_chain_step_enabled",
        "Enable or disable one chain step in place (disabled steps are kept and skipped on run).",
        {
            "step": {"type": "string", "description": "Step id, 1-based position, or name."},
            "enabled": {"type": "boolean"},
        },
        ["step", "enabled"],
    ),
]

# --- F. Markers -------------------------------------------------------------
_MARKER_TOOLS = [
    _fn(
        "set_auto_markers",
        "Choose which markers are AUTO-APPLIED to the images this page GENERATES from now on — like "
        "auto-attaching a label/tag to each new generation. This does NOT tag the current settings "
        "or any existing media, and it does NOT generate anything. Declarative: REPLACES the current "
        "auto-marker selection. Match names against state_context.markers.available; pass [] to stop "
        "auto-marking.",
        {"markers": {"type": "array", "items": {"type": "string"},
                     "description": "marker names to auto-apply to future generations"}},
        ["markers"],
    ),
]

# --- G. Prompt options ------------------------------------------------------
_OPTION_TOOLS = [
    _fn(
        "set_prompt_option",
        "Toggle a prompt option: auto_improve (auto-enhance the prompt before generating) or "
        "vary_prompt (vary the prompt across generations).",
        {"option": {"type": "string", "enum": ["auto_improve", "vary_prompt"]},
         "enabled": {"type": "boolean"}},
        ["option", "enabled"],
    ),
]

# --- G2. Per-tool Instructions ----------------------------------------------
# A single per-tool/preset note (Instructions), co-edited by the user and the
# agent. It rides the state_context every turn, so the agent always sees the
# current text and can target surgical edits. Edits mirror the set_prompt /
# edit_prompt pair (whole-blob set + exact search/replace) so notes edit the
# same way the prompt does.
_NOTES_TOOLS = [
    _fn(
        "set_instructions",
        "Replace the ENTIRE Instructions — the user's standing notes for this tool: preferences and "
        "rules that should shape your future edits (e.g. 'prefer portrait framing', 'whenever there's a "
        "dog make it a great pyrenees', 'keep lighting soft'), plus anything the user asks you to "
        "remember or note here. Use for a full rewrite; empty string clears it; prefer "
        "edit_instructions for small changes. Recording a note does not touch the current prompt; if "
        "the user also wants this image changed now, edit the prompt too.",
        {"content": {"type": "string"}},
        ["content"],
    ),
    _fn(
        "edit_instructions",
        "Surgically edit the Instructions by exact string replacement — the right tool for ADDING one "
        "note or rule, including anything the user asks you to 'remember'. old_string must match the "
        "current Instructions exactly (see state_context.notes); an empty old_string appends. Replaces "
        "the first occurrence unless replace_all is true.",
        {
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean", "description": "Replace all occurrences. Default false."},
        },
        ["old_string", "new_string"],
    ),
]

# --- H. Actions with side effects (Tier 2) ----------------------------------
_ACTION_TOOLS = [
    _fn("generate", "Run generation once with the current settings (same as clicking Run). Only do "
                    "this on explicit user intent, never as a side effect of an edit.", {}),
    _fn(
        "start_forever_mode",
        "Start generate-forever mode. Only on explicit user intent.",
        {"concurrency": {"type": "integer", "description": "Optional; defaults to the current setting."}},
    ),
    _fn("stop_forever_mode", "Stop generate-forever mode.", {}),
]

# --- Undo / redo ------------------------------------------------------------
_HISTORY_TOOLS = [
    _fn(
        "undo",
        "Undo the last change on this screen — exactly like clicking the Undo button. Reverts the "
        "most recent edit (prompt, parameters, images, categories, markers).",
        {},
    ),
    _fn(
        "redo",
        "Redo the change that was just undone — exactly like clicking the Redo button.",
        {},
    ),
]


# --- I. Presets -------------------------------------------------------------
_PRESET_TOOLS = [
    _fn(
        "apply_preset",
        "Load a saved preset by name or id. This REPLACES the current settings (prompt, "
        "parameters, images, etc.). Match against state_context.presets.available. Only on "
        "explicit user request.",
        {"preset": {"type": "string", "description": "preset name or id from state_context.presets"}},
        ["preset"],
    ),
    _fn(
        "save_preset",
        "Save the current settings as a new preset under the given name.",
        {"name": {"type": "string"}},
        ["name"],
    ),
    _fn(
        "reset_to_defaults",
        "Reset all settings to the tool's defaults. This clears the prompt and discards current "
        "settings. Only on explicit user request.",
        {},
    ),
]


TOOL_SCHEMAS: List[Dict[str, Any]] = [
    *_PROMPT_TOOLS,
    *_PARAM_TOOLS,
    *_CATEGORY_TOOLS,
    *_IMAGE_TOOLS,
    *_LORA_TOOLS,
    *_CHAIN_TOOLS,
    *_MARKER_TOOLS,
    *_OPTION_TOOLS,
    *_NOTES_TOOLS,
    *_ACTION_TOOLS,
    *_HISTORY_TOOLS,
    *_PRESET_TOOLS,
]

# Strict function-calling endpoints (e.g. vLLM guided decoding) reject enum
# properties that lack a concrete "type". Ensure every enum is typed as string —
# all our enums are string-valued — so the schema validates everywhere.
for _tool in TOOL_SCHEMAS:
    for _prop in _tool["function"]["parameters"]["properties"].values():
        if "enum" in _prop and "type" not in _prop:
            _prop["type"] = "string"

# Set of valid tool names, for validating tool_calls if needed.
TOOL_NAMES = {t["function"]["name"] for t in TOOL_SCHEMAS}
