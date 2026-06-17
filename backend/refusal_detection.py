"""
Shared refusal classifier — single source of truth for detecting textual
model refusals across all agent surfaces (chat agent main/flow/delegate
and the ToolView prompt agent).

A "refusal" is the model textually declining a request — distinct from a
provider-signaled ``content_filtered`` error, which has a different cause
and a different fix. In telemetry only the categorical label ``refusal``
ever egresses; matched text never leaves the machine.
"""
from typing import Optional

# Common refusal phrasings, matched case-insensitively as substrings.
REFUSAL_PATTERNS = [
    "i cannot",
    "i can't",
    "i'm unable to",
    "i am unable to",
    "i won't",
    "i will not",
    "not appropriate",
    "not able to",
    "cannot assist",
    "can't assist",
    "cannot help",
    "can't help",
    "cannot provide",
    "can't provide",
    "against my",
    "violates",
    "inappropriate",
    "harmful content",
    "explicit content",
    "i apologize",
    "sorry, but",
]


def is_refusal(response_content: Optional[str]) -> bool:
    """True when the response looks like a textual refusal.

    Structured output (JSON arrays/objects) is never classified as a
    refusal even when it contains a matching phrase.
    """
    return detect_refusal(response_content) is not None


def detect_refusal(response_content: Optional[str]) -> Optional[str]:
    """Detect a textual refusal in a model response.

    Returns the leading sentence of the refusal (for in-app display — it
    must NEVER be sent in telemetry; emit the categorical ``refusal``
    label instead), or None when the response is not a refusal.
    """
    if not response_content:
        return None

    clean = response_content.strip()
    # Structured output is a successful answer, not a refusal.
    if clean.startswith("[") or clean.startswith("{"):
        return None

    response_lower = clean.lower()
    for pattern in REFUSAL_PATTERNS:
        if pattern in response_lower:
            first_sentence = (
                clean.split(".")[0] + "." if "." in clean[:200] else clean[:200]
            )
            return first_sentence.strip()

    return None
