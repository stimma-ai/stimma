"""
Model-family munger fixture tests.

Representative real-world model strings (API ids, civitai-style checkpoint
filenames, gguf quant names, file paths) -> expected family. Also asserts
the raw input string never appears in the output — the privacy property
the munger exists for.
"""
import pytest

from model_family import model_family, FAMILY_OTHER, FAMILY_UNKNOWN, SEED_RULES

FIXTURES = [
    # --- FLUX: version lines, not "flux" ---
    ("flux1-dev.safetensors", "flux-1-dev"),
    ("FLUX.1-dev", "flux-1-dev"),
    ("flux1-dev-fp8.safetensors", "flux-1-dev"),
    ("flux1-schnell-Q4_K_M.gguf", "flux-1-schnell"),
    ("flux-1.1-pro", "flux-1.1-pro"),
    ("flux-kontext-max", "flux-kontext"),
    ("flux_klein_9b", "flux-klein"),
    ("FLUX.1-Fill-dev", "flux-1-fill"),
    # --- Stable Diffusion lines ---
    ("sd_xl_base_1.0.safetensors", "sdxl"),
    ("juggernautXL_v9.safetensors", FAMILY_OTHER),  # fine-tune w/o line marker
    ("sdxl-turbo", "sdxl-turbo"),
    ("sd3.5_large_fp8_scaled.safetensors", "sd-3.5"),
    ("v1-5-pruned-emaonly.ckpt", FAMILY_OTHER),  # no recognizable line marker
    ("stable-diffusion-v1-5", "sd-1.5"),
    # --- Qwen ---
    ("qwen-image", "qwen-image"),
    ("qwen-image-edit-2509", "qwen-image-edit"),
    ("Qwen/Qwen3-235B-A22B", "qwen-3"),
    ("qwen2.5-vl-72b-instruct", "qwen-2.5-vl"),
    ("Qwen3-30B-A3B-Q4_K_M.gguf", "qwen-3"),
    # --- Video ---
    ("wan2.2_t2v_high_noise_14B_fp8.safetensors", "wan-2.2"),
    ("wan2.1-i2v-14b-720p", "wan-2.1"),
    ("hunyuan_video_t2v_720p_bf16.safetensors", "hunyuan-video"),
    ("ltx-video-2b-v0.9.safetensors", "ltx-video"),
    # --- Upscale ---
    ("seedvr2_ema_7b_fp16.safetensors", "seedvr2"),
    ("RealESRGAN_x4plus.pth", "esrgan"),
    # --- API LLM ids ---
    ("claude-opus-4-5", "claude-opus-4"),
    ("claude-sonnet-4-20250514", "claude-sonnet-4"),
    ("gpt-4.1-mini", "gpt-4.1-mini"),
    ("gpt-4o", "gpt-4o"),
    ("gpt-oss-120b", "gpt-oss"),
    ("gemini-2.5-flash", "gemini-2.5"),
    ("meta-llama/llama-4-maverick", "llama-4"),
    ("Meta-Llama-3-8B-Instruct.Q5_K_M.gguf", "llama-3"),
    ("deepseek-r1-distill-qwen-32b", "deepseek-r1"),
    ("deepseek-v3-0324", "deepseek-v3"),
    ("mistralai/Mixtral-8x7B-Instruct-v0.1", "mixtral"),
    ("glm-4.5-air", "glm-4"),
    ("kimi-k2-instruct", "kimi-k2"),
    # --- Path-shaped and private-checkpoint-shaped inputs ---
    ("/Users/someone/models/flux1-dev-Q8_0.gguf", "flux-1-dev"),
    ("C:\\models\\checkpoints\\sd_xl_refiner_1.0.safetensors", "sdxl"),
    ("/home/user/secret-client-project-lora-v3.safetensors", FAMILY_OTHER),
    ("my_private_checkpoint_v2.safetensors", FAMILY_OTHER),
    # --- Fallbacks ---
    ("", FAMILY_UNKNOWN),
    (None, FAMILY_UNKNOWN),
    ("completely-novel-model-9000", FAMILY_OTHER),
]


@pytest.mark.parametrize("raw,expected", FIXTURES)
def test_model_family_fixture(raw, expected):
    assert model_family(raw) == expected


@pytest.mark.parametrize("raw,expected", FIXTURES)
def test_raw_input_never_appears_in_output(raw, expected):
    """The privacy property: the output never echoes the input string."""
    family = model_family(raw)
    if raw and len(str(raw)) > len(family):
        assert str(raw).lower() != family
        assert str(raw) not in family
    # Output domain is closed: a known family, other, or unknown.
    known = {fam for _, fam in SEED_RULES}
    assert family in known | {FAMILY_OTHER, FAMILY_UNKNOWN}


def test_quant_variants_collapse_into_version_line():
    variants = [
        "flux1-dev.safetensors",
        "flux1-dev-fp8.safetensors",
        "flux1-dev-Q4_K_M.gguf",
        "flux1-dev-Q8_0.gguf",
        "flux1_dev_bf16.safetensors",
    ]
    assert {model_family(v) for v in variants} == {"flux-1-dev"}
