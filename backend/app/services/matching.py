"""
Keyword matching: case-insensitive, substring, anywhere in the text.
"That is PRICE." matches a rule for "price". Nothing fancier than that
is specified in the README, so nothing fancier is implemented.
"""
from typing import Iterable


def find_matching_rules(comment_text: str, rules: Iterable[dict]) -> list[dict]:
    if not comment_text:
        return []
    haystack = comment_text.lower()
    return [r for r in rules if r["keyword"].lower() in haystack]
