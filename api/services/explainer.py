"""(profile, zone) -> Why-Here narrative. The prompt receives only the numbers the
scoring engine already computed (zone's sub-scores, gap, competitors, anchors, rent) and
is forbidden from inventing any other number. `has_invented_numbers` enforces that after
the fact: any live response containing a number untraceable to `zone` is discarded in
favor of a templated sentence built solely from those same computed numbers."""
import re

from api.models import ConceptProfile
from api.services import llm_client

SUBSCORE_LABELS = {
    "D": "Demand", "C": "Competition", "T": "Traffic fit", "A": "Access",
    "S_spend": "Spending fit", "K": "Cost fit", "Sup": "Supplier proximity",
}

PROMPT_TEMPLATE = """You are Forkcast's site-selection explainer for "{concept_name}" ({cuisines}).
Narrate ONLY the numbers listed below -- do not invent, estimate, round to a new figure, or
compute any number that is not already given. If the rent estimate is null, say rent is unknown;
never guess a figure.

Sub-scores (0-100 percentile): {subscores}
Demand/supply/gap: {gap}
Confidence: {confidence}
Direct competitors: {competitors_direct}
Indirect competitors: {competitors_indirect}
Anchors nearby: {anchors}
Estimated rent ($/sqft/yr): {rent} (rent confidence: {rent_confidence})

Write, in plain text: two "why here" drivers with numbers, three advantage bullets, two-to-three
risk bullets drawn from the weakest sub-scores, and a nearby section naming the competitors and
anchors above.
"""


def _numbers_in(value) -> set[str]:
    """Every numeric leaf in a nested dict/list/scalar, rendered a few plausible ways
    (bare, 0dp, 1dp, 2dp) so a legitimate restatement of an input number is recognized."""
    found: set[str] = set()

    def add(n):
        for s in (str(n), f"{n:.0f}", f"{n:.1f}", f"{n:.2f}"):
            found.add(s)
        if 0 <= n <= 1:  # a 0-1 fraction (confidence, importance) is often narrated as a percent
            add_pct(n * 100)

    def add_pct(n):
        for s in (str(n), f"{n:.0f}", f"{n:.1f}"):
            found.add(s)

    def walk(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            add(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(value)
    return found


def _output_numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+\.?\d*", text))


def has_invented_numbers(text: str, zone: dict) -> bool:
    """True if `text` contains a number that cannot be traced back to `zone`."""
    allowed = _numbers_in(zone)
    for tok in _output_numbers(text):
        bare = tok.lstrip("0") or "0"
        if tok not in allowed and bare not in allowed:
            return True
    return False


def _fallback_template(profile: ConceptProfile, zone: dict) -> str:
    """Templated sentence built only from the computed numbers already in `zone`."""
    subscores = {k: v for k, v in (zone.get("subscores") or {}).items() if v is not None}
    ranked = sorted(subscores.items(), key=lambda kv: -kv[1])
    drivers = [f"{SUBSCORE_LABELS.get(k, k)} {v:.0f}th pct" for k, v in ranked[:2]]
    weakest = [f"{SUBSCORE_LABELS.get(k, k)} {v:.0f}th pct" for k, v in ranked[-2:][::-1]]
    rent = zone.get("est_rent_psf_yr")
    rent_conf = zone.get("rent_confidence") or 0
    rent_sentence = ("Rent is unknown for this cell (no estimate available)."
                      if rent is None else
                      f"Estimated rent is ${rent:.0f}/sqft/yr (confidence {rent_conf:.0%}).")
    direct = zone.get("competitors_direct") or []
    comp_sentence = (f"Direct competitors nearby: {', '.join(c['name'] for c in direct)}."
                      if direct else "No direct competitors were found nearby.")
    total = zone.get("total")
    confidence = zone.get("confidence") or 0
    total_sentence = f"Overall score {total:.0f} (confidence {confidence:.0%})." if total is not None else ""
    return (
        f"Why here for {profile.concept_name}: {'; '.join(drivers) or 'no sub-scores available'}. "
        f"{total_sentence} "
        f"Weakest areas: {'; '.join(weakest) or 'none'}. "
        f"{comp_sentence} {rent_sentence}"
    ).strip()


def explain(profile: ConceptProfile, zone: dict) -> str:
    prompt = PROMPT_TEMPLATE.format(
        concept_name=profile.concept_name,
        cuisines=", ".join(profile.cuisines),
        subscores=zone.get("subscores"),
        gap=zone.get("gap"),
        confidence=zone.get("confidence"),
        competitors_direct=zone.get("competitors_direct"),
        competitors_indirect=zone.get("competitors_indirect"),
        anchors=zone.get("anchors"),
        rent=zone.get("est_rent_psf_yr"),
        rent_confidence=zone.get("rent_confidence"),
    )
    cache_input = f"{zone.get('zone_id')}|{zone.get('best_h3')}|{profile.concept_name}"
    text = llm_client.generate_text("explain", cache_input=cache_input, prompt=prompt)
    if text is None or has_invented_numbers(text, zone):
        return _fallback_template(profile, zone)
    return text
