"""
LLM service for text processing.

This module provides a simple interface for text completions
used by ingestion and other services.
"""
import asyncio
from typing import Optional, List
from core.logging import get_logger

from config import LLMConfig
from llm import llm_complete_text, llm_complete_batch

log = get_logger(__name__)


class LLMService:
    def __init__(self, config: LLMConfig, max_parallelism: int = 50):
        self.config = config
        self.max_parallelism = max_parallelism

    async def complete(self, prompt: str) -> tuple[Optional[str], Optional[str]]:
        try:
            messages = [{"role": "user", "content": prompt}]
            result = await llm_complete_text(
                config=self.config,
                messages=messages,
                max_tokens=100,
                temperature=0.1,
            )
            return result, None
        except asyncio.TimeoutError:
            return None, "Request timeout"
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            log.error(f"LLM: {error_msg}")
            return None, error_msg

    async def complete_batch(self, prompts: List[str]) -> List[tuple[Optional[str], Optional[str]]]:
        return await llm_complete_batch(
            config=self.config,
            prompts=prompts,
            max_tokens=100,
            temperature=0.1,
            max_concurrency=self.max_parallelism,
        )

    async def close(self):
        pass
