"""Weight validation (forkcast-proposal.md §5.5).

`validate()` is the single gate between LLM-proposed weights and anything persisted to
`analyses.weights_json`: clamp each weight to [0, 1], cap any single weight at 0.4 (no one
sub-score may dominate), drop any key not in `available` (today that's "K" -- rent is NULL
on every cell), and renormalize the remainder to sum to 1.0.
"""
from api.models import SUBSCORE_KEYS

MAX_WEIGHT = 0.4

# §5.5 defaults by service_format.
DEFAULT_WEIGHTS_BY_FORMAT: dict[str, dict[str, float]] = {
    "quick_service": {"D": .25, "C": .18, "T": .22, "A": .15, "S_spend": .08, "K": .09, "Sup": .03},
    "fast_casual":   {"D": .25, "C": .18, "T": .22, "A": .15, "S_spend": .08, "K": .09, "Sup": .03},
    "casual_dining": {"D": .25, "C": .18, "T": .12, "A": .12, "S_spend": .15, "K": .12, "Sup": .06},
    "fine_dining":   {"D": .18, "C": .15, "T": .08, "A": .10, "S_spend": .25, "K": .15, "Sup": .09},
    "cafe":          {"D": .25, "C": .15, "T": .25, "A": .17, "S_spend": .08, "K": .07, "Sup": .03},
    "bar":           {"D": .25, "C": .15, "T": .25, "A": .17, "S_spend": .08, "K": .07, "Sup": .03},
    "ghost_kitchen": {"D": .40, "C": .15, "T": .05, "A": .00, "S_spend": .05, "K": .25, "Sup": .10},
}

DEFAULT_WEIGHTS: dict[str, float] = DEFAULT_WEIGHTS_BY_FORMAT["casual_dining"]


def defaults_for(service_format: str) -> dict[str, float]:
    return dict(DEFAULT_WEIGHTS_BY_FORMAT.get(service_format, DEFAULT_WEIGHTS))


def validate(proposed: dict[str, float], available: set[str]) -> dict[str, float]:
    """Clamp to [0,1], cap at MAX_WEIGHT, zero out keys not in `available`, renormalize
    the rest to sum 1.0. `available` is trusted as given -- this function does no data
    lookups of its own; the caller (engine.analyze()) is responsible for computing it
    correctly (K excluded while est_rent_psf_yr is NULL on every cell).

    Every key in SUBSCORE_KEYS is always present in the result, because
    contracts/recommend_response.json requires all seven. An unavailable sub-score gets
    weight 0.0, which is the honest value: it contributes nothing to the total. That is a
    different statement from the sub-score itself, which stays None because the input was
    never measured. Dropping the key instead would violate the frozen contract."""
    cleaned: dict[str, float] = {}
    for k in SUBSCORE_KEYS:
        if k not in available:
            cleaned[k] = 0.0
            continue
        w = proposed.get(k, 0.0)
        try:
            w = float(w)
        except (TypeError, ValueError):
            w = 0.0
        if w != w:  # NaN
            w = 0.0
        w = max(0.0, min(1.0, w))
        w = min(w, MAX_WEIGHT)
        cleaned[k] = w

    total = sum(cleaned.values())
    if total <= 0:
        # every proposed weight was 0/missing/absent: fall back to the format defaults,
        # restricted to what's available.
        cleaned = {k: (DEFAULT_WEIGHTS.get(k, 0.0) if k in available else 0.0)
                   for k in SUBSCORE_KEYS}
        total = sum(cleaned.values())
    if total <= 0:
        # available itself doesn't overlap the defaults (or is empty): split evenly
        # across what is available, still emitting every key.
        n = len(available) or 1
        return {k: (1.0 / n if k in available else 0.0) for k in SUBSCORE_KEYS}
    return {k: v / total for k, v in cleaned.items()}
