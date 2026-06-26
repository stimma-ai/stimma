"""
Model-family munger — the single source of truth mapping any model string
(API model id, checkpoint filename, .gguf path, STP-declared model) to a
closed ``modelFamily`` value for telemetry.

Only the family ever egresses; the raw string never leaves the machine —
so the input can be anything, including a user's private checkpoint name,
and the output domain is still a closed list we ship.

Mechanics:
- The input is normalized to its basename (path stripped), lowercased,
  with the file extension and common quant/precision/fine-tune suffixes
  removed before matching.
- Rules are an ORDERED, first-match-wins list of (case-insensitive regex,
  family). Granularity is the model VERSION LINE, not the manufacturer:
  flux-1-dev, flux-1-schnell, flux-1.1-pro, and flux-kontext are four
  families, not "flux". Quant/precision/fine-tune variants collapse into
  the line.
- No rule matches -> "other". No model string available -> "unknown".

The rules table is hardcoded for now and treated as a normal catalog
asset, updated as models ship. The design anticipates later delivery via
feature flags (the rules list as a flag value); the privacy property holds
as long as the rules are never user-configurable.
"""
import re
from typing import List, Optional, Tuple

FAMILY_OTHER = "other"
FAMILY_UNKNOWN = "unknown"

# Strip common quant / precision / packaging suffixes from the normalized
# basename before matching, so "flux1-dev-Q4_K_M" and "flux1-dev-fp8" both
# land in flux-1-dev.
_STRIP_EXTENSIONS = (
    ".safetensors", ".ckpt", ".gguf", ".pt", ".pth", ".bin", ".onnx", ".sft",
)
_QUANT_SUFFIX_RE = re.compile(
    r"([._-](q\d(_[a-z0-9]+)*|iq\d(_[a-z0-9]+)*|f16|f32|fp4|fp8|fp16|fp32|bf16|"
    r"int4|int8|nf4|awq|gptq|gguf|exl2|mlx|e4m3fn|e5m2|scaled|"
    r"4bit|8bit|4b|8b(it)?-quant|quantized|distilled|pruned|ema(only)?|"
    r"v\d+(\.\d+)*[a-z]?))+$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# seed table — review pending
#
# Ordered, first-match-wins. Most-specific patterns first within each line.
# Covers the model lines visible in the app/tool surface plus the obvious
# public image/video/LLM lines. Update via the normal catalog process.
# ---------------------------------------------------------------------------
SEED_RULES: List[Tuple[str, str]] = [
    # --- FLUX lines ---
    (r"flux[ ._-]?1[ ._-]?1.*pro|flux.*1\.1.*pro", "flux-1.1-pro"),
    (r"flux.*kontext", "flux-kontext"),
    (r"flux.*krea", "flux-krea"),
    (r"flux.*klein", "flux-klein"),
    (r"flux.*fill", "flux-1-fill"),
    (r"flux.*(canny|depth|redux)", "flux-1-tools"),
    (r"flux.*schnell", "flux-1-schnell"),
    (r"flux[ ._-]?(1[ ._-]?)?dev|flux.*\bdev\b", "flux-1-dev"),
    (r"flux[ ._-]?pro", "flux-1-pro"),
    (r"flux[ ._-]?2", "flux-2"),
    (r"flux", "flux-other"),
    # --- Stable Diffusion lines ---
    (r"sd[ ._-]?xl.*turbo|sdxl[ ._-]?turbo", "sdxl-turbo"),
    (r"sd[ ._-]?xl.*lightning", "sdxl-lightning"),
    (r"s(table[ ._-]?diffusion|d)[ ._-]?xl|sdxl", "sdxl"),
    (r"s(table[ ._-]?diffusion|d)[ ._-]?3[ ._-]?5|sd3\.5", "sd-3.5"),
    (r"s(table[ ._-]?diffusion|d)[ ._-]?3", "sd-3"),
    (r"s(table[ ._-]?diffusion|d)[ ._-]?2", "sd-2"),
    (r"s(table[ ._-]?diffusion|d)[ ._-]?(v?1[ ._-]?5|1\.5)", "sd-1.5"),
    (r"stable[ ._-]?cascade", "stable-cascade"),
    (r"stable[ ._-]?video|svd", "stable-video-diffusion"),
    # --- DeepSeek (before Qwen: r1-distill-qwen names belong to the r1 line) ---
    (r"deepseek[ ._-]?r1", "deepseek-r1"),
    (r"deepseek[ ._-]?v3", "deepseek-v3"),
    (r"deepseek[ ._-]?v2", "deepseek-v2"),
    (r"deepseek", "deepseek-other"),
    # --- Qwen image / VL / LLM lines ---
    (r"qwen[ ._-]?image[ ._-]?edit", "qwen-image-edit"),
    (r"qwen[ ._-]?image", "qwen-image"),
    (r"qwen[ ._-]?3(?!\d)", "qwen-3"),
    (r"qwen[ ._-]?2[ ._-]?5.*vl|qwen2\.5-vl", "qwen-2.5-vl"),
    (r"qwen[ ._-]?2[ ._-]?5", "qwen-2.5"),
    (r"qwen[ ._-]?2(?!\d)", "qwen-2"),
    (r"qwq", "qwq"),
    (r"qwen", "qwen-other"),
    # --- Video lines ---
    (r"wan[ ._-]?2[ ._-]?2|wan2\.2", "wan-2.2"),
    (r"wan[ ._-]?2[ ._-]?1|wan2\.1", "wan-2.1"),
    (r"\bwan\b|wan[ ._-]?video", "wan-other"),
    (r"hunyuan[ ._-]?video", "hunyuan-video"),
    (r"hunyuan[ ._-]?image", "hunyuan-image"),
    (r"hunyuan", "hunyuan-other"),
    (r"\bltx\b|ltx[ ._-]?v(ideo)?|ltx[ ._-]?\d", "ltx-video"),
    (r"mochi", "mochi"),
    (r"cogvideo", "cogvideo"),
    (r"veo[ ._-]?3", "veo-3"),
    (r"veo[ ._-]?2", "veo-2"),
    (r"kling", "kling"),
    (r"runway|gen[ ._-]?4", "runway-gen"),
    (r"sora", "sora"),
    (r"seedance", "seedance"),
    # --- Upscalers / restoration ---
    (r"seedvr[ ._-]?2|seedvr2", "seedvr2"),
    (r"esrgan|realesrgan", "esrgan"),
    (r"supir", "supir"),
    (r"gfpgan|codeformer", "face-restore"),
    # --- Other image lines ---
    (r"hidream", "hidream"),
    (r"chroma", "chroma"),
    (r"pixart", "pixart"),
    (r"playground[ ._-]?v?2", "playground-2"),
    (r"kolors", "kolors"),
    (r"lumina", "lumina"),
    (r"omnigen", "omnigen"),
    (r"auraflow", "auraflow"),
    (r"seedream", "seedream"),
    (r"recraft", "recraft"),
    (r"ideogram", "ideogram"),
    (r"midjourney|mj[ ._-]?v\d", "midjourney"),
    (r"nano[ ._-]?banana", "nano-banana"),
    (r"imagen[ ._-]?4", "imagen-4"),
    (r"imagen[ ._-]?3", "imagen-3"),
    (r"imagen", "imagen-other"),
    (r"dall[ ._-]?e[ ._-]?3", "dall-e-3"),
    (r"dall[ ._-]?e", "dall-e-other"),
    (r"gpt[ ._-]?image", "gpt-image"),
    # --- Anthropic ---
    (r"claude.*opus[ ._-]?4", "claude-opus-4"),
    (r"claude.*sonnet[ ._-]?4", "claude-sonnet-4"),
    (r"claude.*haiku[ ._-]?4", "claude-haiku-4"),
    (r"claude.*3[ ._-]?7", "claude-3.7"),
    (r"claude.*3[ ._-]?5", "claude-3.5"),
    (r"claude.*3", "claude-3"),
    (r"claude", "claude-other"),
    # --- OpenAI LLMs ---
    (r"gpt[ ._-]?oss", "gpt-oss"),
    (r"gpt[ ._-]?5[ ._-]?mini", "gpt-5-mini"),
    (r"gpt[ ._-]?5[ ._-]?nano", "gpt-5-nano"),
    (r"gpt[ ._-]?5", "gpt-5"),
    (r"gpt[ ._-]?4\.1[ ._-]?mini", "gpt-4.1-mini"),
    (r"gpt[ ._-]?4\.1", "gpt-4.1"),
    (r"gpt[ ._-]?4o[ ._-]?mini", "gpt-4o-mini"),
    (r"gpt[ ._-]?4o", "gpt-4o"),
    (r"gpt[ ._-]?4", "gpt-4-other"),
    (r"\bo3[ ._-]?mini\b", "o3-mini"),
    (r"\bo3\b", "o3"),
    (r"\bo4[ ._-]?mini\b", "o4-mini"),
    (r"\bo1\b", "o1"),
    (r"chatgpt|gpt[ ._-]?3\.5", "gpt-3.5"),
    # --- Google LLMs ---
    (r"gemini[ ._-]?3", "gemini-3"),
    (r"gemini[ ._-]?2[ ._-]?5", "gemini-2.5"),
    (r"gemini[ ._-]?2", "gemini-2.0"),
    (r"gemini[ ._-]?1[ ._-]?5", "gemini-1.5"),
    (r"gemini", "gemini-other"),
    (r"gemma[ ._-]?3", "gemma-3"),
    (r"gemma", "gemma-other"),
    # --- Meta ---
    (r"llama[ ._-]?4", "llama-4"),
    (r"llama[ ._-]?3", "llama-3"),
    (r"llama[ ._-]?2", "llama-2"),
    (r"llama", "llama-other"),
    # --- Mistral ---
    (r"mixtral", "mixtral"),
    (r"mistral[ ._-]?(small|medium|large)", "mistral-smol"),
    (r"magistral", "magistral"),
    (r"devstral", "devstral"),
    (r"mistral|ministral|pixtral", "mistral-other"),
    # --- Other open LLM lines ---
    (r"glm[ ._-]?4", "glm-4"),
    (r"glm", "glm-other"),
    (r"kimi[ ._-]?k2", "kimi-k2"),
    (r"kimi", "kimi-other"),
    (r"phi[ ._-]?4", "phi-4"),
    (r"phi[ ._-]?3", "phi-3"),
    (r"grok[ ._-]?4", "grok-4"),
    (r"grok[ ._-]?3", "grok-3"),
    (r"grok", "grok-other"),
    (r"command[ ._-]?r", "command-r"),
    (r"minimax", "minimax"),
    (r"smollm", "smollm"),
    (r"olmo", "olmo"),
    (r"nemotron", "nemotron"),
    (r"hermes", "hermes"),
    (r"vicuna", "vicuna"),
    (r"falcon", "falcon"),
    (r"yi[ ._-]?1[ ._-]?5|^yi[ ._-]", "yi"),
    # --- Speech / embeddings used in-app ---
    (r"whisper", "whisper"),
    (r"clip|vit[ ._-]?g|vit[ ._-]?l|vit[ ._-]?b", "clip"),
]

_COMPILED_RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(pattern, re.IGNORECASE), family) for pattern, family in SEED_RULES
]


def normalize_model_string(model: str) -> str:
    """Normalize a model string for matching.

    Strips directory components, file extension, and trailing quant /
    precision suffixes; lowercases. Never returned or transmitted —
    matching input only.
    """
    s = (model or "").strip().lower()
    # Path components (posix and windows)
    s = s.replace("\\", "/").rsplit("/", 1)[-1]
    for ext in _STRIP_EXTENSIONS:
        if s.endswith(ext):
            s = s[: -len(ext)]
            break
    # Provider prefixes in API ids (e.g. "qwen/qwen3-235b", "accounts/...").
    # rsplit on '/' above already handled these; also strip an org colon
    # prefix like "openrouter:meta-llama/...".
    if ":" in s:
        s = s.rsplit(":", 1)[-1]
    # Iteratively strip quant/precision suffix groups.
    prev = None
    while prev != s:
        prev = s
        s = _QUANT_SUFFIX_RE.sub("", s)
    return s.strip(" ._-")


def model_family(model: Optional[str]) -> str:
    """Map a model string to its closed modelFamily value.

    Returns ``unknown`` when no model string is available, ``other`` when
    no rule matches. Never returns the input.
    """
    if not model or not str(model).strip():
        return FAMILY_UNKNOWN
    normalized = normalize_model_string(str(model))
    if not normalized:
        return FAMILY_UNKNOWN
    for pattern, family in _COMPILED_RULES:
        if pattern.search(normalized):
            return family
    return FAMILY_OTHER
