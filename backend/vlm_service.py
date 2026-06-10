"""
VLM service for vision-language tasks using litellm.

This module provides an interface for visual analysis (caption + keywords).
"""
import base64
import asyncio
import json
from pathlib import Path
from typing import Optional, Union, List
from PIL import Image
import io
from core.logging import get_logger

from config import LLMConfig
from llm import llm_complete_vision

log = get_logger(__name__)


class VLMService:
    def __init__(
        self,
        config: LLMConfig,
        analysis_prompt: str,
        max_parallelism: int = 50
    ):
        """
        Initialize VLM service for visual analysis.

        Args:
            config: LLMConfig with provider, model, and optional endpoint
            analysis_prompt: Prompt for visual analysis (returns JSON with caption + keywords)
            max_parallelism: Maximum concurrent requests
        """
        self.config = config
        self.analysis_prompt = analysis_prompt
        self.semaphore = asyncio.Semaphore(max_parallelism)
        self._active_requests = 0
        log.info(f"VLM SERVICE: Initialized with max_parallelism={max_parallelism}")

    def encode_image_base64(self, image_input: Union[Path, Image.Image]) -> str:
        """Encode image to base64 string. Accepts either Path or PIL Image."""
        # Open image if it's a path, otherwise use the provided Image
        if isinstance(image_input, Path):
            img = Image.open(image_input)
            should_close = True
        else:
            img = image_input
            should_close = False

        try:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # Resize if too large (to save bandwidth)
            max_size = 1024
            if max(img.size) > max_size:
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

            # Convert to base64
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=90)
            img_bytes = buffer.getvalue()
            return base64.b64encode(img_bytes).decode('utf-8')
        finally:
            # Only close if we opened it
            if should_close:
                img.close()

    async def analyze_image(self, image_input: Union[Path, Image.Image]) -> tuple[Optional[str], Optional[List[str]], Optional[str]]:
        """
        Analyze an image and return both caption and keywords in one VLM call.

        Args:
            image_input: Either a Path to an image file or a PIL Image object

        Returns:
            Tuple of (caption text or None, keywords list or None, error message or None)
        """
        async with self.semaphore:
            self._active_requests += 1
            try:
                image_desc = str(image_input) if isinstance(image_input, Path) else "PIL Image"
                log.debug(f"VLM ANALYSIS: [{self._active_requests} active] Starting: {image_desc}")

                # Encode image
                image_b64 = self.encode_image_base64(image_input)
                log.debug(f"VLM ANALYSIS: Image encoded ({len(image_b64)} bytes base64)")

                # Make completion call with vision
                response, error = await llm_complete_vision(
                    config=self.config,
                    prompt=self.analysis_prompt,
                    image_b64=image_b64,
                    max_tokens=800,
                    temperature=0.3,
                )

                if error:
                    log.error(f"VLM ANALYSIS: {error} for {image_desc}")
                    return None, None, error

                # Check for empty response
                if not response:
                    error_msg = "Empty response from LLM"
                    log.error(f"VLM ANALYSIS: {error_msg} for {image_desc}")
                    return None, None, error_msg

                # Parse JSON response
                try:
                    # Try to extract JSON from the response
                    # Sometimes models wrap JSON in markdown code blocks
                    response_text = response.strip()
                    if response_text.startswith("```json"):
                        response_text = response_text[7:]
                    if response_text.startswith("```"):
                        response_text = response_text[3:]
                    if response_text.endswith("```"):
                        response_text = response_text[:-3]
                    response_text = response_text.strip()

                    data = json.loads(response_text)
                    caption = data.get("caption")
                    keywords = data.get("keywords", [])

                    # Validate
                    if not caption:
                        log.warning(f"VLM ANALYSIS: No caption in JSON response for {image_desc}")
                        return None, None, "No caption in response"

                    if not isinstance(keywords, list):
                        keywords = []

                    # Normalize keywords: lowercase, strip, limit to 15
                    keywords = [str(kw).strip().lower() for kw in keywords if kw][:15]

                    log.debug(f"VLM ANALYSIS: ✓ {image_desc} - caption: '{caption[:80]}...' - {len(keywords)} keywords")
                    return caption, keywords, None

                except json.JSONDecodeError as e:
                    log.warning(f"VLM ANALYSIS: JSON parse error for {image_desc}: {e}")
                    log.warning(f"VLM ANALYSIS: Raw response: {response[:500]}")

                    # Fallback: treat the entire response as a caption with no keywords
                    # This handles models that don't follow JSON instructions
                    if response and len(response) > 50:
                        log.info(f"VLM ANALYSIS: Falling back to raw response as caption for {image_desc}")
                        return response.strip(), [], None

                    return None, None, f"JSON parse error: {e}"

            except asyncio.TimeoutError:
                error_msg = "Request timeout (>60s)"
                log.error(f"VLM ANALYSIS: {error_msg} for {image_desc}")
                return None, None, error_msg
            except FileNotFoundError:
                # Don't log at error - caller will handle marking file unavailable
                error_msg = f"FileNotFoundError: {image_desc}"
                return None, None, error_msg
            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)}"
                log.error(f"VLM ANALYSIS: {error_msg} for {image_desc}")
                return None, None, error_msg
            finally:
                self._active_requests -= 1

    async def analyze_batch(self, image_paths: List[Path]) -> List[tuple[Optional[str], Optional[List[str]], Optional[str]]]:
        """
        Analyze multiple images in parallel.

        Args:
            image_paths: List of image paths

        Returns:
            List of (caption, keywords, error) tuples (same order as input)
        """
        tasks = [self.analyze_image(path) for path in image_paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error tuples
        analyses = []
        for result in results:
            if isinstance(result, Exception):
                error_msg = f"{type(result).__name__}: {str(result)}"
                log.error(f"Batch analysis error: {error_msg}")
                analyses.append((None, None, error_msg))
            else:
                analyses.append(result)

        return analyses

    async def close(self):
        """Close the service. No-op for litellm (no persistent connections)."""
        pass
