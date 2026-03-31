from dataclasses import dataclass

@dataclass(frozen=True)
class TrendRunLimits:
    # Discovery
    max_candidates: int = 25
    max_extracts: int = 6
    max_per_domain: int = 2

    # Stage 1 (compression)
    max_article_chars: int = 3500

    # Stage 2 (synthesis)
    max_cards: int = 6

    # Token safety
    max_completion_tokens: int = 3000