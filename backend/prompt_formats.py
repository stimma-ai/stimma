"""Agent-facing model input requirements, independent of enhancement defaults."""

from __future__ import annotations


def prompt_format_requirements(label: str) -> dict:
    """Describe the model's input contract; this does not enforce enhancement."""
    if label == "MiniMax H3":
        return {
            "required": True,
            "reference": ".stimma/prompt-formats/minimax-h3.md",
        }
    return {"required": False}


def prompt_format_guidance(label: str) -> str:
    requirements = prompt_format_requirements(label)
    if requirements["required"]:
        return (
            f"{label} requires its documented prompt format. Enhancement produces it "
            "automatically by default; set enhance_prompt=False when supplying that "
            "format yourself or reusing an already formatted prompt. "
            f"Read {requirements['reference']} before writing it yourself. "
            "Disabling enhancement leaves the model's input requirements unchanged."
        )
    return (
        f"{label} has a recommended prompt style; enhancement applies it by default. "
        "Set enhance_prompt=False to retain your wording, for example for controlled "
        "variations. The result's .sent_prompt shows any rewritten prompt."
    )


def render_h3_prompt_reference() -> str:
    """Project the enhancer's live format and alignment rules into readable docs."""
    from prompts import get_prompt
    from routes.prompt_enhancement import (
        _h3_audio_guidance,
        _h3_dialogue_guidance,
        _h3_task_guidance,
    )

    template = get_prompt("prompt_enhancement", "improve_minimax_h3_system_prompt")
    dialogue = (
        "When no dialogue is supplied:\n" + _h3_dialogue_guidance("")
        + "\n\nWhen dialogue is supplied:\n"
        + _h3_dialogue_guidance("<d>[English] Supplied words.</d>")
    )
    audio = (
        _h3_audio_guidance(True) + "\n\n" + _h3_audio_guidance(False)
    )
    for placeholder, value in {
        "h3_task_guidance": "Use the input alignment rules below for the actual inputs.",
        "h3_dialogue_guidance": dialogue,
        "h3_audio_guidance": audio,
        "protected_text_guidance": "Preserve supplied dialogue and visible text verbatim.",
    }.items():
        template = template.replace("{" + placeholder + "}", value)

    sections = [
        "# MiniMax H3 prompt format\n\n"
        "This format is required whether you write the prompt yourself or use enhancement. "
        "These instructions come from the same source as automatic enhancement.\n\n"
        + template.strip(),
        "## Input alignment\n\n"
        "Choose the case matching the actual inputs. Examples below use a 15-second "
        "target; substitute the actual duration and reference tags. Shot numbers refer "
        "to the shots you wrote. Keep a continuous take in one shot; introduce a new "
        "shot label only for an intended cut.",
    ]
    for task, heading in (
        ("t2va", "Text only"),
        ("i2va", "First frame"),
        ("fl2va", "First and last frames"),
        ("l2va", "Last frame only"),
        ("ref2va", "References and keyframes"),
    ):
        references = [
            {"label": "Picture 1", "kind": "image"},
            {"label": "Audio 1", "kind": "video_audio"},
            {"label": "Video 1", "kind": "video"},
            {"label": "Audio 2", "kind": "audio"},
        ] if task == "ref2va" else []
        sections.append(f"### {heading}\n\n" + _h3_task_guidance(task, 15, references))
    sections.append(
        "For reference-to-video, the tag mapping above is illustrative. Use the actual "
        "input presentation order described by the tool. A video with sound contributes "
        "separate audio and video tags; standalone audio follows those references. "
        "Keyframes pin moments on the target timeline rather than receiving reference "
        "tags. Describe their actual times and carry motion and sound through pinned clips."
    )
    return "\n\n".join(sections) + "\n"
