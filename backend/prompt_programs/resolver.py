"""Class resolver: which vocabulary class a pick's spec names, or none.

A pick's `about` ("her hairstyle") may name a curated class (`person.hair`) whose
options are written once and shared. Choosing the class is a choice question for the
decision model over class names, asked after prepare. There is no vocabulary yet, so
every pick resolves to none and its options come from the generator.
"""

from __future__ import annotations

from typing import Optional, Protocol

from prompt_programs.draws import PickSpec


class ClassResolver(Protocol):
    version: str

    def resolve(self, spec: PickSpec) -> Optional[str]:
        """The class name for this pick, or None to generate its options."""
        ...


class NoVocabulary:
    """Every pick resolves to none."""
    version = "none"

    def resolve(self, spec: PickSpec) -> Optional[str]:
        return None


__all__ = ["ClassResolver", "NoVocabulary"]
