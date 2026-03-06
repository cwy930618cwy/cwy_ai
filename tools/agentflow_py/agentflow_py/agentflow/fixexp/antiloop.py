"""Anti-loop detection: 3-level prevention."""
import hashlib
import logging
from typing import Dict, List, Optional, Tuple


def _feature_hash(text: str) -> str:
    return hashlib.md5(text.lower().strip().encode()).hexdigest()


def _jaccard_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity between two strings (word-level)."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


class AntiLoopDetector:
    def __init__(self, warn_threshold: float = 0.6, block_threshold: float = 0.85,
                 max_same_approach: int = 2):
        self.warn_threshold = warn_threshold
        self.block_threshold = block_threshold
        self.max_same_approach = max_same_approach

    def check(self, new_approach: str, previous_approaches: List[str]) -> Tuple[str, str]:
        """
        Returns (level, message) where level = "ok" | "warn" | "block".
        """
        if not previous_approaches:
            return "ok", ""

        new_hash = _feature_hash(new_approach)

        # Level 3: Exact same approach (hash match)
        hash_count = sum(
            1 for pa in previous_approaches if _feature_hash(pa) == new_hash
        )
        if hash_count >= self.max_same_approach:
            return "block", (
                f"⛔ 检测到同一方案尝试超过{self.max_same_approach}次，强制阻断。请从根本上改变思路。"
            )

        # Level 2: High similarity (block_threshold)
        for pa in previous_approaches:
            sim = _jaccard_similarity(new_approach, pa)
            if sim >= self.block_threshold:
                return "block", (
                    f"⛔ 与之前方案相似度过高({sim:.0%})，强制阻断。请尝试完全不同的思路。"
                )

        # Level 1: Moderate similarity (warn_threshold)
        for pa in previous_approaches:
            sim = _jaccard_similarity(new_approach, pa)
            if sim >= self.warn_threshold:
                return "warn", (
                    f"⚠️ 与之前方案相似度较高({sim:.0%})，请谨慎考虑是否是新思路。"
                )

        return "ok", ""
