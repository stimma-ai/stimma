"""Parameter specification system for task implementations."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class ParamType(str, Enum):
    """Types of parameters that can be declared."""

    INT = "int"
    FLOAT = "float"
    STRING = "string"
    BOOL = "bool"
    ENUM = "enum"  # String with specific choices
    LORA_LIST = "lora_list"  # Special type for LoRA selections
    LORA_PAIR = "lora_pair"  # Special type for paired LoRA selection (high/low noise)


@dataclass
class ParameterSpec:
    """
    Specification for a single parameter supported by a task implementation.

    Used to:
    - Declare which parameters an implementation supports
    - Define defaults, constraints, and UI hints
    - Generate JSON schema for frontend consumption
    - Validate parameter values
    """

    name: str
    param_type: ParamType
    default: Any
    description: str = ""

    # Constraints
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    step: Optional[Union[int, float]] = None  # For sliders
    choices: Optional[List[str]] = None  # For enum type

    # UI hints
    ui_group: str = "general"  # e.g., "sampling", "advanced", "model"
    ui_order: int = 0
    hidden: bool = False  # Hide from UI but still accept

    def validate(self, value: Any) -> tuple[bool, Optional[str]]:
        """
        Validate a value against this parameter spec.

        Returns:
            Tuple of (is_valid, error_message). error_message is None if valid.
        """
        if value is None:
            return True, None  # None is acceptable, will use default

        if self.param_type == ParamType.INT:
            if not isinstance(value, int) or isinstance(value, bool):
                return False, f"{self.name} must be an integer"
            if self.min_value is not None and value < self.min_value:
                return False, f"{self.name} must be >= {self.min_value}"
            if self.max_value is not None and value > self.max_value:
                return False, f"{self.name} must be <= {self.max_value}"

        elif self.param_type == ParamType.FLOAT:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False, f"{self.name} must be a number"
            if self.min_value is not None and value < self.min_value:
                return False, f"{self.name} must be >= {self.min_value}"
            if self.max_value is not None and value > self.max_value:
                return False, f"{self.name} must be <= {self.max_value}"

        elif self.param_type == ParamType.STRING:
            if not isinstance(value, str):
                return False, f"{self.name} must be a string"

        elif self.param_type == ParamType.BOOL:
            if not isinstance(value, bool):
                return False, f"{self.name} must be a boolean"

        elif self.param_type == ParamType.ENUM:
            if self.choices and value not in self.choices:
                return False, f"{self.name} must be one of {self.choices}"

        elif self.param_type == ParamType.LORA_LIST:
            if not isinstance(value, list):
                return False, f"{self.name} must be a list"
            # Each item should be a dict with 'lora' and 'weight'
            for item in value:
                if not isinstance(item, dict):
                    return False, f"{self.name} items must be objects"
                if "lora" not in item:
                    return False, f"{self.name} items must have 'lora' field"

        elif self.param_type == ParamType.LORA_PAIR:
            if value is not None and not isinstance(value, dict):
                return False, f"{self.name} must be an object or null"
            if value is not None:
                if "high_noise_path" not in value or "low_noise_path" not in value:
                    return False, f"{self.name} must have 'high_noise_path' and 'low_noise_path' fields"

        return True, None

    def to_json_schema(self) -> Dict[str, Any]:
        """Convert to JSON Schema fragment for UI consumption."""
        schema: Dict[str, Any] = {
            "title": self.name.replace("_", " ").title(),
            "description": self.description,
            "default": self.default,
            "x-ui-group": self.ui_group,
            "x-ui-order": self.ui_order,
            "x-hidden": self.hidden,
        }

        if self.param_type == ParamType.INT:
            schema["type"] = "integer"
            if self.min_value is not None:
                schema["minimum"] = int(self.min_value)
            if self.max_value is not None:
                schema["maximum"] = int(self.max_value)
            if self.step is not None:
                schema["x-step"] = int(self.step)

        elif self.param_type == ParamType.FLOAT:
            schema["type"] = "number"
            if self.min_value is not None:
                schema["minimum"] = self.min_value
            if self.max_value is not None:
                schema["maximum"] = self.max_value
            if self.step is not None:
                schema["x-step"] = self.step

        elif self.param_type == ParamType.STRING:
            schema["type"] = "string"

        elif self.param_type == ParamType.BOOL:
            schema["type"] = "boolean"

        elif self.param_type == ParamType.ENUM:
            schema["type"] = "string"
            schema["enum"] = self.choices or []

        elif self.param_type == ParamType.LORA_LIST:
            schema["type"] = "array"
            schema["items"] = {
                "type": "object",
                "properties": {
                    "lora": {"type": "string"},
                    "weight": {"type": "number", "default": 1.0},
                    "enabled": {"type": "boolean", "default": True},
                },
                "required": ["lora"],
            }

        elif self.param_type == ParamType.LORA_PAIR:
            schema["type"] = "object"
            schema["properties"] = {
                "name": {"type": "string"},
                "high_noise_path": {"type": "string"},
                "low_noise_path": {"type": "string"},
            }
            schema["required"] = ["high_noise_path", "low_noise_path"]
            schema["nullable"] = True

        return schema


# Common parameter definitions that implementations can reuse
COMMON_PARAMETERS = {
    "prompt": ParameterSpec(
        name="prompt",
        param_type=ParamType.STRING,
        default="",
        description="The text prompt describing what to generate",
        ui_group="general",
        ui_order=0,
    ),
    "negative_prompt": ParameterSpec(
        name="negative_prompt",
        param_type=ParamType.STRING,
        default="ugly, cartoon, 3d, video game, cg",
        description="What to avoid in the generation",
        ui_group="advanced",
        ui_order=10,
    ),
    "width": ParameterSpec(
        name="width",
        param_type=ParamType.INT,
        default=848,
        description="Image width in pixels",
        min_value=256,
        max_value=4096,
        step=64,
        ui_group="resolution",
        ui_order=0,
    ),
    "height": ParameterSpec(
        name="height",
        param_type=ParamType.INT,
        default=1152,
        description="Image height in pixels",
        min_value=256,
        max_value=4096,
        step=64,
        ui_group="resolution",
        ui_order=1,
    ),
    "cfg": ParameterSpec(
        name="cfg",
        param_type=ParamType.FLOAT,
        default=4.0,
        description="Classifier-free guidance scale",
        min_value=1.0,
        max_value=30.0,
        step=0.1,
        ui_group="sampling",
        ui_order=0,
    ),
    "guidance": ParameterSpec(
        name="guidance",
        param_type=ParamType.FLOAT,
        default=3.5,
        description="Guidance scale for flow models",
        min_value=1.0,
        max_value=10.0,
        step=0.1,
        ui_group="sampling",
        ui_order=0,
    ),
    "steps": ParameterSpec(
        name="steps",
        param_type=ParamType.INT,
        default=20,
        description="Number of sampling steps",
        min_value=1,
        max_value=150,
        step=1,
        ui_group="sampling",
        ui_order=1,
    ),
    "sampler": ParameterSpec(
        name="sampler",
        param_type=ParamType.ENUM,
        default="euler",
        description="Sampling algorithm",
        choices=[
            "euler",
            "euler_cfg_pp",
            "euler_ancestral",
            "euler_ancestral_cfg_pp",
            "heun",
            "heunpp2",
            "dpm_2",
            "dpm_2_ancestral",
            "lms",
            "dpm_fast",
            "dpm_adaptive",
            "dpmpp_2s_ancestral",
            "dpmpp_2s_ancestral_cfg_pp",
            "dpmpp_sde",
            "dpmpp_sde_gpu",
            "dpmpp_2m",
            "dpmpp_2m_cfg_pp",
            "dpmpp_2m_sde",
            "dpmpp_2m_sde_gpu",
            "dpmpp_2m_sde_heun",
            "dpmpp_2m_sde_heun_gpu",
            "dpmpp_3m_sde",
            "dpmpp_3m_sde_gpu",
            "ddpm",
            "lcm",
            "ipndm",
            "ipndm_v",
            "deis",
            "res_multistep",
            "res_multistep_cfg_pp",
            "res_multistep_ancestral",
            "res_multistep_ancestral_cfg_pp",
            "gradient_estimation",
            "gradient_estimation_cfg_pp",
            "er_sde",
            "seeds_2",
            "seeds_3",
            "sa_solver",
            "sa_solver_pece",
            "ddim",
            "uni_pc",
        ],
        ui_group="sampling",
        ui_order=2,
    ),
    "scheduler": ParameterSpec(
        name="scheduler",
        param_type=ParamType.ENUM,
        default="simple",
        description="Noise schedule",
        choices=[
            "normal",
            "karras",
            "exponential",
            "sgm_uniform",
            "simple",
            "ddim_uniform",
            "beta",
            "linear_quadratic",
            "kl_optimal",
        ],
        ui_group="sampling",
        ui_order=3,
    ),
    "seed": ParameterSpec(
        name="seed",
        param_type=ParamType.INT,
        default=None,
        description="Random seed for reproducibility",
        min_value=0,
        max_value=2**32 - 1,
        ui_group="advanced",
        ui_order=0,
    ),
    "denoise": ParameterSpec(
        name="denoise",
        param_type=ParamType.FLOAT,
        default=1.0,
        description="Denoising strength",
        min_value=0.0,
        max_value=1.0,
        step=0.05,
        ui_group="advanced",
        ui_order=1,
    ),
    "shift": ParameterSpec(
        name="shift",
        param_type=ParamType.FLOAT,
        default=3.0,
        description="AuraFlow/SD3 shift parameter",
        min_value=0.0,
        max_value=10.0,
        step=0.1,
        ui_group="advanced",
        ui_order=2,
    ),
    "megapixels": ParameterSpec(
        name="megapixels",
        param_type=ParamType.FLOAT,
        default=1.0,
        description="Target megapixels for scaling",
        min_value=0.25,
        max_value=4.0,
        step=0.1,
        ui_group="resolution",
        ui_order=2,
    ),
    "loras": ParameterSpec(
        name="loras",
        param_type=ParamType.LORA_LIST,
        default=[],
        description="LoRA models to apply",
        ui_group="model",
        ui_order=0,
    ),
    # Video-specific parameters
    "frame_count": ParameterSpec(
        name="frame_count",
        param_type=ParamType.INT,
        default=81,
        description="Number of frames to generate",
        min_value=17,
        max_value=161,
        step=8,
        ui_group="video",
        ui_order=0,
    ),
    "fps": ParameterSpec(
        name="fps",
        param_type=ParamType.INT,
        default=16,
        description="Frames per second",
        min_value=8,
        max_value=30,
        step=1,
        ui_group="video",
        ui_order=1,
    ),
    "lightning": ParameterSpec(
        name="lightning",
        param_type=ParamType.BOOL,
        default=False,
        description="Use Lightning mode (faster, forces cfg=1.0)",
        ui_group="model",
        ui_order=0,
    ),
    "selected_lora_pair": ParameterSpec(
        name="selected_lora_pair",
        param_type=ParamType.LORA_PAIR,
        default=None,
        description="Paired LoRA for high/low noise sampling (Lightning mode)",
        ui_group="model",
        ui_order=1,
    ),
    "duration": ParameterSpec(
        name="duration",
        param_type=ParamType.FLOAT,
        default=5.0,
        description="Video duration in seconds",
        min_value=1.0,
        max_value=15.0,
        step=0.5,
        ui_group="video",
        ui_order=0,
    ),
}
