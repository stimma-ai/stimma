from pathlib import Path
from typing import Optional
from PIL import Image
from PIL.ExifTags import TAGS
from core.logging import get_logger
import json
import piexif

log = get_logger(__name__)


def extract_prompt_from_exif(file_path: Path) -> tuple[Optional[str], Optional[str]]:
    """
    Extract AI generation prompt from image EXIF data.

    Looks for common metadata fields used by AI image generators:
    - 'prompt' (ComfyUI, Automatic1111)
    - 'UserComment' (some generators)
    - 'ImageDescription' (some generators)
    - PNG 'parameters' chunk (Automatic1111)
    - PNG 'Dream' chunk (Midjourney)

    Returns:
        Tuple of (raw_metadata, parsed_prompt) - raw is the JSON blob, parsed is the human-readable prompt
    """
    raw_metadata = None
    parsed_prompt = None

    try:
        # For PNG files, check PNG chunks first
        if file_path.suffix.lower() == '.png':
            raw_metadata = extract_from_png_chunks(file_path)
            if raw_metadata:
                parsed_prompt = parse_prompt_from_metadata(raw_metadata)
                return raw_metadata, parsed_prompt

        # Try EXIF data
        with Image.open(file_path) as img:
            # Get EXIF data
            exif_data = img.getexif()
            if not exif_data:
                return None, None

            # Convert to readable format (IFD0 tags)
            exif_dict = {
                TAGS.get(key, key): value
                for key, value in exif_data.items()
            }

            # Also check Exif IFD for UserComment (tag 37510) - PIL's getexif()
            # only returns IFD0 tags, but UserComment is in the Exif sub-IFD
            if 'UserComment' not in exif_dict:
                try:
                    exif_ifd = exif_data.get_ifd(0x8769)  # Exif IFD
                    if exif_ifd and 37510 in exif_ifd:
                        user_comment_raw = exif_ifd[37510]
                        if isinstance(user_comment_raw, bytes):
                            # Decode based on charset marker
                            user_comment_text = _decode_exif_user_comment(user_comment_raw)
                            if user_comment_text:
                                exif_dict['UserComment'] = user_comment_text
                except Exception:
                    pass

            # Check common prompt fields
            for field in ['prompt', 'Prompt', 'UserComment', 'ImageDescription', 'XPComment']:
                if field in exif_dict:
                    value = exif_dict[field]
                    if isinstance(value, bytes):
                        try:
                            value = value.decode('utf-8', errors='ignore')
                        except:
                            continue

                    # Clean up the value
                    value = str(value).strip()

                    # Check if it looks like a prompt (not empty, not just metadata)
                    if value and len(value) > 10:
                        raw_metadata = value
                        parsed_prompt = parse_prompt_from_metadata(value)
                        return raw_metadata, parsed_prompt

            return None, None

    except Exception as e:
        log.debug(f"Failed to extract EXIF from {file_path}: {e}")
        return None, None


def _is_comfyui_format(data: dict) -> bool:
    """Check if dict looks like ComfyUI prompt format."""
    # ComfyUI has node IDs as keys, each with class_type
    for key, value in data.items():
        if isinstance(value, dict) and 'class_type' in value:
            return True
    return False


def _is_fooocus_format(data: dict) -> bool:
    """Check if dict looks like Fooocus metadata."""
    fooocus_keys = {'Prompt', 'FullPrompt', 'full_prompt',
                    'NegativePrompt', 'FullNegativePrompt', 'full_negative_prompt'}
    return bool(fooocus_keys & set(data.keys()))


def _extract_prompt_a1111(metadata: str) -> Optional[str]:
    """
    Extract positive prompt from A1111/Forge metadata format.

    Format: [positive prompt]\\nNegative prompt: [negative]\\nSteps: 20, ...
    """
    # Split on "Negative prompt:" - text before it is the positive prompt
    if "Negative prompt:" in metadata:
        parts = metadata.split("Negative prompt:", 1)
        prompt = parts[0].strip()
        if prompt:
            return prompt

    # No negative prompt marker - check if it's just prompt + params
    if "Steps:" in metadata:
        # Find where parameters start (look for common param patterns)
        lines = metadata.split('\n')
        prompt_lines = []
        for line in lines:
            # Stop when we hit parameter lines
            if any(line.strip().startswith(p) for p in ['Steps:', 'Sampler:', 'CFG', 'Size:', 'Model:']):
                break
            prompt_lines.append(line)
        prompt = '\n'.join(prompt_lines).strip()
        if prompt:
            return prompt

    return None


def _extract_prompt_fooocus(data: dict) -> Optional[str]:
    """
    Extract prompt from Fooocus metadata format.

    Fooocus stores prompts in 'Prompt' (string) or 'FullPrompt' (array).
    Prefer the non-expanded 'Prompt' over 'FullPrompt'.
    """
    # Prefer simple string prompt over expanded array
    for key in ['Prompt', 'prompt']:
        if key in data:
            val = data[key]
            if isinstance(val, str) and val.strip():
                return val.strip()

    # Try array versions (FullPrompt contains expanded prompt with styles)
    for key in ['FullPrompt', 'full_prompt']:
        if key in data:
            val = data[key]
            if isinstance(val, list) and val:
                # Join array or take first non-empty element
                if isinstance(val[0], str):
                    return val[0].strip() if val[0].strip() else None
            elif isinstance(val, str) and val.strip():
                return val.strip()

    return None


def _walk_to_text(data: dict, connection, visited: set = None, depth: int = 0) -> Optional[str]:
    """
    Recursively walk the ComfyUI node graph from a connection to find text.

    Args:
        data: The full prompt dict (node_id -> node)
        connection: Either a [node_id, output_index] array or a direct value
        visited: Set of visited node IDs to prevent cycles
        depth: Current depth to prevent infinite recursion

    Returns:
        The text content if found, None otherwise
    """
    if visited is None:
        visited = set()

    if depth > 20:  # Prevent runaway recursion
        return None

    # If connection is a string, we found text!
    if isinstance(connection, str):
        return connection

    # If connection is [node_id, output_index], follow it
    if isinstance(connection, list) and len(connection) >= 2:
        node_id = str(connection[0])
        if node_id in visited:
            return None
        visited.add(node_id)

        node = data.get(node_id)
        if not node:
            return None

        inputs = node.get('inputs', {})

        # Check for text in this node (common field names)
        for key in ['text', 'text_g', 'prompt', 'string', 'text_positive']:
            if key in inputs:
                val = inputs[key]
                if isinstance(val, str):
                    return val
                # It might be another connection, recurse
                result = _walk_to_text(data, val, visited, depth + 1)
                if result:
                    return result

        # No direct text, try following any connection inputs
        for key, val in inputs.items():
            if isinstance(val, list) and len(val) >= 2:
                result = _walk_to_text(data, val, visited, depth + 1)
                if result:
                    return result

    return None


def _extract_prompt_comfyui(data: dict) -> Optional[str]:
    """
    Extract positive prompt from ComfyUI workflow by walking the node graph.

    Strategy:
    1. Find any node with a "positive" input and walk backwards to find text
    2. Fallback: collect all text from CLIPTextEncode nodes, return longest
    """
    # Step 1: Find any node with a "positive" input
    for node_id, node in data.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get('inputs', {})
        if 'positive' in inputs:
            # Walk backwards from the positive connection
            text = _walk_to_text(data, inputs['positive'])
            if text:
                return text

    # Fallback: find all text from CLIPTextEncode-like nodes, return longest
    texts = []
    for node_id, node in data.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get('class_type', '')
        # Match any CLIP text encoding node
        if 'CLIPTextEncode' in class_type or 'TextEncode' in class_type:
            inputs = node.get('inputs', {})
            for key in ['text', 'text_g', 'prompt', 'string']:
                if key in inputs and isinstance(inputs[key], str):
                    text = inputs[key].strip()
                    if text:
                        texts.append(text)

    if texts:
        # Return the longest text (usually the positive prompt is more detailed)
        return max(texts, key=len)

    return None


def parse_prompt_from_metadata(metadata_str: str) -> Optional[str]:
    """
    Parse the actual human-readable prompt from metadata string.

    Handles multiple formats:
    - ComfyUI: Complex JSON with node graph
    - Fooocus: JSON with Prompt/FullPrompt keys
    - A1111/Forge: Plain text with "Negative prompt:" separator
    """
    if not metadata_str:
        return None

    # Try JSON parse first
    if metadata_str.strip().startswith('{'):
        try:
            data = json.loads(metadata_str)

            # ComfyUI: has node IDs as keys with class_type
            if _is_comfyui_format(data):
                return _extract_prompt_comfyui(data)

            # Fooocus: has Prompt/FullPrompt keys
            if _is_fooocus_format(data):
                return _extract_prompt_fooocus(data)

        except json.JSONDecodeError:
            pass

    # A1111: plain text with "Negative prompt:" or "Steps:" marker
    if "Negative prompt:" in metadata_str or "Steps:" in metadata_str:
        return _extract_prompt_a1111(metadata_str)

    # Fallback: return as-is if it looks like a prompt (not too long, few params)
    if len(metadata_str) < 2000 and metadata_str.count(':') < 5:
        return metadata_str.strip()

    return None


def extract_from_png_chunks(file_path: Path) -> Optional[str]:
    """
    Extract raw metadata string from PNG chunks.

    PNG files from AI generators often have custom chunks like 'parameters'.
    Returns the raw metadata without parsing - parsing is done by parse_prompt_from_metadata().
    """
    try:
        with Image.open(file_path) as img:
            if hasattr(img, 'info'):
                # Check fields in priority order
                for field in ['parameters', 'Parameters', 'prompt', 'Prompt', 'Dream', 'dream', 'Comment']:
                    if field in img.info:
                        value = img.info[field]
                        if isinstance(value, bytes):
                            value = value.decode('utf-8', errors='ignore')
                        value = str(value).strip()
                        if value and len(value) > 10:
                            return value  # Return raw, don't parse
        return None

    except Exception as e:
        log.debug(f"Failed to extract PNG chunks from {file_path}: {e}")
        return None


def extract_stimma_metadata(file_path: Path) -> Optional[str]:
    """
    Extract 'stimma' generation metadata from image.

    First tries to extract from EXIF UserComment (survives browser drag-drop, works for PNG and JPEG),
    then falls back to PNG text chunks (backwards compatibility, PNG only).

    Returns:
        JSON string of stimma metadata, or None if not found
    """
    try:
        suffix = file_path.suffix.lower()
        # Only process PNG and JPEG files
        if suffix not in ['.png', '.jpg', '.jpeg']:
            return None

        with Image.open(file_path) as img:
            # First, try to extract from EXIF UserComment (more robust, works for both PNG and JPEG)
            try:
                if "exif" in img.info:
                    exif_dict = piexif.load(img.info["exif"])
                    if "Exif" in exif_dict and piexif.ExifIFD.UserComment in exif_dict["Exif"]:
                        user_comment = exif_dict["Exif"][piexif.ExifIFD.UserComment]

                        # EXIF UserComment format: [Character Code] + [Actual String]
                        # We stored it as "ASCII\x00\x00\x00" + JSON
                        if user_comment.startswith(b"ASCII\x00\x00\x00"):
                            metadata_json = user_comment[8:].decode('utf-8')
                            # Validate it's our stimma metadata (accept both old "stimmer" and new "stimma")
                            try:
                                parsed = json.loads(metadata_json)
                                if isinstance(parsed, dict) and parsed.get("source") in ("stimmer", "stimma"):
                                    return metadata_json
                            except json.JSONDecodeError:
                                pass
            except Exception as e:
                log.debug(f"Failed to extract EXIF UserComment from {file_path}: {e}")

            # Fall back to PNG text chunks (backwards compatibility, PNG only)
            # Check both new 'stimma' and old 'stimmer' keys
            if suffix == '.png' and hasattr(img, 'info'):
                if 'stimma' in img.info:
                    return img.info['stimma']
                elif 'stimmer' in img.info:
                    return img.info['stimmer']

        return None

    except Exception as e:
        log.debug(f"Failed to extract stimma metadata from {file_path}: {e}")
        return None


def extract_generation_metadata(file_path: Path) -> dict:
    """
    Extract all available AI generation metadata from an image.

    Returns:
        Dictionary with extracted metadata
    """
    metadata = {
        "prompt": None,
        "negative_prompt": None,
        "model": None,
        "sampler": None,
        "steps": None,
        "cfg_scale": None,
        "seed": None,
    }

    try:
        prompt = extract_prompt_from_exif(file_path)
        if prompt:
            metadata["prompt"] = prompt

            # Try to parse additional parameters from the prompt string
            # Many generators include all params in one field
            if "Negative prompt:" in prompt:
                parts = prompt.split("Negative prompt:")
                metadata["prompt"] = parts[0].strip()
                metadata["negative_prompt"] = parts[1].strip().split("\n")[0].strip()

            # Parse steps, CFG, etc. (common format: "Steps: 20, CFG scale: 7, ...")
            if "Steps:" in prompt:
                for line in prompt.split("\n"):
                    if "Steps:" in line:
                        try:
                            params = line.split(",")
                            for param in params:
                                param = param.strip()
                                if param.startswith("Steps:"):
                                    metadata["steps"] = int(param.split(":")[1].strip())
                                elif "CFG scale:" in param:
                                    metadata["cfg_scale"] = float(param.split(":")[1].strip())
                                elif "Seed:" in param:
                                    metadata["seed"] = int(param.split(":")[1].strip())
                                elif "Sampler:" in param:
                                    metadata["sampler"] = param.split(":")[1].strip()
                                elif "Model:" in param:
                                    metadata["model"] = param.split(":")[1].strip()
                        except:
                            pass

    except Exception as e:
        log.debug(f"Failed to extract generation metadata from {file_path}: {e}")

    return metadata


def extract_a1111_params(file_path: Path) -> Optional[str]:
    """
    Extract the raw A1111-style 'parameters' chunk from a PNG image.

    This returns the complete parameters string as-is, suitable for
    inheritance when upscaling or editing an image.

    Args:
        file_path: Path to the PNG image file

    Returns:
        The raw parameters string, or None if not found
    """
    try:
        suffix = file_path.suffix.lower()
        if suffix != '.png':
            return None

        with Image.open(file_path) as img:
            if hasattr(img, 'info') and 'parameters' in img.info:
                value = img.info['parameters']
                if isinstance(value, bytes):
                    value = value.decode('utf-8', errors='ignore')
                return str(value).strip() if value else None

        return None

    except Exception as e:
        log.debug(f"Failed to extract A1111 parameters from {file_path}: {e}")
        return None


def _decode_exif_user_comment(raw: bytes) -> Optional[str]:
    """Decode EXIF UserComment bytes, handling charset markers."""
    if raw.startswith(b'ASCII\x00\x00\x00'):
        return raw[8:].decode('ascii', errors='ignore').strip()
    elif raw.startswith(b'UNICODE\x00'):
        # Try UTF-16 BE (most common for UNICODE marker)
        try:
            return raw[8:].decode('utf-16-be', errors='ignore').strip()
        except Exception:
            pass
    elif raw.startswith(b'\x00\x00\x00\x00\x00\x00\x00\x00'):
        # Undefined charset, try UTF-8
        return raw[8:].decode('utf-8', errors='ignore').strip()
    else:
        # No marker, try UTF-8
        try:
            return raw.decode('utf-8', errors='ignore').strip()
        except Exception:
            pass
    return None


import re


def _extract_json_value(s: str) -> Optional[str]:
    """Extract a balanced JSON array or object from the start of a string."""
    if not s:
        return None
    opener = s[0]
    if opener == '[':
        closer = ']'
    elif opener == '{':
        closer = '}'
    else:
        return None

    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(s):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return s[:i + 1]
    return None


def parse_a1111_parameters(raw_metadata: str) -> Optional[dict]:
    """
    Parse A1111/Forge-style metadata string into a structured dict.

    Format: [positive prompt]\nNegative prompt: [negative]\nKey: value, Key: value, ...
    """
    if not raw_metadata or "Steps:" not in raw_metadata:
        return None

    try:
        # Split into: positive prompt, negative prompt, parameter line
        positive_prompt = ""
        negative_prompt = ""
        param_line = ""

        if "Negative prompt:" in raw_metadata:
            parts = raw_metadata.split("Negative prompt:", 1)
            positive_prompt = parts[0].strip()
            remainder = parts[1]

            # Find where the parameter line starts - look for \nSteps:
            steps_match = re.search(r'\n(Steps:\s*\d+)', remainder)
            if steps_match:
                negative_prompt = remainder[:steps_match.start()].strip()
                param_line = remainder[steps_match.start():].strip()
            else:
                negative_prompt = remainder.strip()
        elif "Steps:" in raw_metadata:
            # No negative prompt, find where params start
            steps_match = re.search(r'\n?(Steps:\s*\d+)', raw_metadata)
            if steps_match:
                positive_prompt = raw_metadata[:steps_match.start()].strip()
                param_line = raw_metadata[steps_match.start():].strip()

        # Extract JSON-valued fields before comma-splitting
        # These contain commas that would break naive splitting
        json_fields = {}
        for json_key in ['Civitai resources', 'Civitai metadata']:
            marker = json_key + ': '
            idx = param_line.find(marker)
            if idx == -1:
                continue
            json_start = idx + len(marker)
            json_str = _extract_json_value(param_line[json_start:])
            if json_str:
                try:
                    json_fields[json_key] = json.loads(json_str)
                    # Remove from param_line to avoid breaking comma split
                    end_idx = json_start + len(json_str)
                    param_line = param_line[:idx].rstrip(', ') + param_line[end_idx:]
                except json.JSONDecodeError:
                    pass

        # Parse remaining Key: value pairs from parameter line
        params_raw = {}
        if param_line:
            # Split by comma, then parse key: value
            for part in param_line.split(','):
                part = part.strip()
                if ':' in part:
                    key, _, value = part.partition(':')
                    key = key.strip()
                    value = value.strip()
                    if key and value:
                        params_raw[key] = value

        # Build structured result
        parameters = {}

        # Map known fields with type conversion
        if 'Steps' in params_raw:
            try:
                parameters['steps'] = int(params_raw['Steps'])
            except ValueError:
                pass
        if 'Sampler' in params_raw:
            parameters['sampler'] = params_raw['Sampler']
        if 'CFG scale' in params_raw:
            try:
                parameters['cfg'] = float(params_raw['CFG scale'])
            except ValueError:
                pass
        if 'Seed' in params_raw:
            try:
                parameters['seed'] = int(params_raw['Seed'])
            except ValueError:
                pass
        if 'Size' in params_raw:
            size_match = re.match(r'(\d+)x(\d+)', params_raw['Size'])
            if size_match:
                parameters['width'] = int(size_match.group(1))
                parameters['height'] = int(size_match.group(2))
        if 'Clip skip' in params_raw:
            try:
                parameters['clip_skip'] = int(params_raw['Clip skip'])
            except ValueError:
                pass

        # Determine checkpoint name from params or Civitai resources
        checkpoint = params_raw.get('Model', '')
        loras = []

        civitai_resources = json_fields.get('Civitai resources', [])
        if isinstance(civitai_resources, list):
            for resource in civitai_resources:
                if not isinstance(resource, dict):
                    continue
                rtype = resource.get('type', '')
                if rtype == 'checkpoint':
                    checkpoint = resource.get('modelName', checkpoint)
                elif rtype == 'lora':
                    lora_name = resource.get('modelName', 'Unknown LoRA')
                    lora_weight = resource.get('weight', 1.0)
                    loras.append({'name': lora_name, 'weight': lora_weight})

        if checkpoint:
            parameters['checkpoint'] = checkpoint

        # Parse generated_at from Created Date
        generated_at = None
        if 'Created Date' in params_raw:
            try:
                # Format: 2025-02-10T14:33:38.3245072Z
                date_str = params_raw['Created Date']
                # Truncate sub-second precision and Z for ISO parsing
                date_str = re.sub(r'\.\d+Z?$', '', date_str)
                date_str = date_str.rstrip('Z')
                generated_at = date_str
            except Exception:
                pass

        result = {
            "source": "external",
            "format": "a1111",
            "model": checkpoint or None,
            "generator": "Stable Diffusion",
            "prompt": positive_prompt or None,
            "negative_prompt": negative_prompt or None,
            "parameters": parameters,
            "generated_at": generated_at,
            "loras": loras if loras else None,
            "source_inputs": [],
        }

        return result

    except Exception as e:
        log.debug(f"Failed to parse A1111 parameters: {e}")
        return None


def parse_external_metadata(raw_metadata: str) -> Optional[dict]:
    """
    Detect external metadata format and parse into structured dict.

    Currently supports A1111/Forge format. ComfyUI/Fooocus can be added later.
    """
    if not raw_metadata:
        return None

    # A1111/Forge: plain text with "Steps:" marker
    if "Steps:" in raw_metadata and not raw_metadata.strip().startswith('{'):
        return parse_a1111_parameters(raw_metadata)

    # Future: ComfyUI, Fooocus, etc.
    return None
