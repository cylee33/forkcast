"""The app's one state hook, mirroring `web`'s single `useAnalysis` hook: all
cross-widget state (profile, center/radius, last analysis, selected zone, active map
layer, mode) lives in one place instead of being scattered across ad hoc
`st.session_state` keys through the rendering code.
"""

from __future__ import annotations

import streamlit as st

# Pittsburgh (Oakland), matching the proposal's default demo pin.
DEFAULT_CENTER = {"lat": 40.4406, "lng": -79.9600}
DEFAULT_RADIUS_MI = 3.0

DEMO_CONCEPTS = [
    "Cheap Korean street food under $15 for college students, open late.",
    "Premium Korean BBQ, $50/person, groups, parking.",
    "Family steak & seafood, big dining room, parking, weekend dinners.",
]

LAYER_OPTIONS = {
    "Opportunity (total)": "total",
    "Demand": "D",
    "Competition": "C",
    "Traffic": "T",
    "Access": "A",
    "Spending": "S_spend",
    "Cost": "K",
    "Supply": "Sup",
}


def init_state() -> "st.session_state":
    """Ensure every key this app reads exists, without clobbering a rerun's state."""
    ss = st.session_state
    ss.setdefault("concept_text", "")
    ss.setdefault("profile", None)  # ConceptProfile dict, once parsed
    ss.setdefault("center", dict(DEFAULT_CENTER))
    ss.setdefault("radius_mi", DEFAULT_RADIUS_MI)
    ss.setdefault("analysis", None)  # last RecommendResponse dict
    ss.setdefault("analysis_source", None)  # "api" | "fixture"
    ss.setdefault("analysis_message", None)
    ss.setdefault("selected_zone_id", None)
    ss.setdefault("active_layer", "total")
    ss.setdefault("mode", "forward")  # "forward" | "reverse"
    ss.setdefault("last_refine_diff", None)
    ss.setdefault("why_here", {})  # zone_id -> explain() response or fallback text
    return ss


def set_analysis(ss, data: dict, source: str, message: str | None) -> None:
    ss["analysis"] = data
    ss["analysis_source"] = source
    ss["analysis_message"] = message
    ss["profile"] = data.get("profile", ss.get("profile"))
    ss["selected_zone_id"] = None
    ss["why_here"] = {}
