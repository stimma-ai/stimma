from tool_provider_identity import (
    STIMMA_TOOL_PROVIDER_DISPLAY_NAME,
    STIMMA_TOOL_PROVIDER_ID,
    tool_provider_display_name,
)


def test_stimma_tool_provider_has_canonical_display_name():
    assert STIMMA_TOOL_PROVIDER_ID == "stimma-cloud"
    assert STIMMA_TOOL_PROVIDER_DISPLAY_NAME == "Stimma"
    assert tool_provider_display_name("stimma-cloud", "Stimma Cloud") == "Stimma"


def test_other_tool_provider_names_are_unchanged():
    assert tool_provider_display_name("comfyui", "ComfyUI") == "ComfyUI"
