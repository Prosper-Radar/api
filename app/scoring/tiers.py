"""
Grille de tiers Prosper — source de vérité unique.

Si ces seuils changent, il faut recomputer tout l'historique deal_scores.
Voir QA_GUIDELINES.md § « Scoring grid ».
"""

TIER_A_THRESHOLD: float = 70.0
TIER_B_THRESHOLD: float = 45.0


def total_to_tier(total: float) -> str:
    """Convertit un total_score (0-100) en tier A / B / C."""
    if total >= TIER_A_THRESHOLD:
        return "A"
    if total >= TIER_B_THRESHOLD:
        return "B"
    return "C"
