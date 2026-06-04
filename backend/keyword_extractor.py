import re
from typing import List, Set
from collections import Counter
from core.logging import get_logger

log = get_logger(__name__)

# Common stop words to filter out
STOP_WORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'has', 'he',
    'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the', 'to', 'was', 'were',
    'will', 'with', 'this', 'there', 'their', 'which', 'she', 'or', 'but',
    'been', 'have', 'had', 'not', 'they', 'can', 'all', 'would', 'what',
    'when', 'where', 'who', 'how', 'out', 'up', 'down', 'over', 'under'
}

# Minimum word length for keywords
MIN_WORD_LENGTH = 3


def extract_keywords(text: str, max_keywords: int = 30) -> List[str]:
    """
    Extract keywords from text using simple NLP techniques.

    Args:
        text: Input text (caption, prompt, or both)
        max_keywords: Maximum number of keywords to return

    Returns:
        List of keyword strings
    """
    if not text:
        return []

    # Convert to lowercase
    text = text.lower()

    # Extract words (alphanumeric sequences)
    words = re.findall(r'\b[a-z][a-z0-9]*\b', text)

    # Filter words
    filtered_words = []
    for word in words:
        # Skip stop words
        if word in STOP_WORDS:
            continue

        # Skip very short words
        if len(word) < MIN_WORD_LENGTH:
            continue

        # Skip numbers only
        if word.isdigit():
            continue

        filtered_words.append(word)

    # Count word frequencies
    word_counts = Counter(filtered_words)

    # Extract common noun phrases (simple bigrams and trigrams)
    bigrams = []
    for i in range(len(words) - 1):
        if words[i] not in STOP_WORDS or words[i+1] not in STOP_WORDS:
            bigram = f"{words[i]} {words[i+1]}"
            if len(bigram) >= MIN_WORD_LENGTH * 2:
                bigrams.append(bigram)

    bigram_counts = Counter(bigrams)

    # Combine single words and phrases
    # Give phrases higher weight
    all_keywords = []

    # Add frequent bigrams first
    for phrase, count in bigram_counts.most_common(max_keywords // 3):
        if count > 1:  # Only include if appears multiple times
            all_keywords.append(phrase)

    # Add single words
    for word, count in word_counts.most_common(max_keywords):
        if word not in all_keywords:
            all_keywords.append(word)

    # Limit to max_keywords
    return all_keywords[:max_keywords]


def extract_keywords_from_multiple_sources(*texts: str, max_keywords: int = 30) -> List[str]:
    """
    Extract keywords from multiple text sources (e.g., caption + prompt).

    Args:
        *texts: Variable number of text strings
        max_keywords: Maximum number of keywords

    Returns:
        List of keywords extracted from all sources combined
    """
    # Combine all texts
    combined_text = ' '.join(filter(None, texts))

    # Extract keywords
    return extract_keywords(combined_text, max_keywords)


def keywords_to_string(keywords: List[str]) -> str:
    """Convert keyword list to comma-separated string for storage."""
    return ','.join(keywords)


def string_to_keywords(keywords_str: str) -> List[str]:
    """Convert comma-separated string back to keyword list."""
    if not keywords_str:
        return []
    return [k.strip() for k in keywords_str.split(',') if k.strip()]
