"""Forkcast — interactive Streamlit interface.

Run with: `streamlit run app/streamlit_app.py`

Calls the FastAPI service over HTTP (`FORKCAST_API`, default `http://localhost:8000`) —
never imports `api/scoring` or `api/services` directly, so the API is genuinely
exercised. Falls back to the committed fixture (`data/fixtures/recommend_sample.json`)
whenever the service is unreachable, so the app runs standalone. See `app/api_client.py`
for the HTTP + fallback logic and `app/formatting.py` for the pure rendering helpers
(unit tested in `app/test_app.py`).
"""

from __future__ import annotations

import pydeck as pdk
import streamlit as st

from app import api_client, state
from app.formatting import (
    PROXY_SUBSCORES,
    SUBSCORE_KEYS,
    SUBSCORE_LABELS,
    apply_refine_response,
    build_hex_records,
    color_for_score,
    competitor_caveat,
    format_backtest_rho,
    format_rent,
    format_score,
    rank_zones,
    score_bar_fraction,
    traffic_provenance_note,
)

DAYPART_KEYS = ["breakfast", "lunch", "dinner", "late_night", "weekend"]
IMPORTANCE_KEYS = [
    "dine_in_importance",
    "takeout_importance",
    "delivery_importance",
    "parking_importance",
    "pedestrian_importance",
    "transit_importance",
    "nightlife_importance",
    "office_importance",
    "university_importance",
    "family_importance",
    "visibility_importance",
]

st.set_page_config(page_title="Forkcast", page_icon="🍜", layout="wide")

st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem; max-width: 1200px;}
    h1, h2, h3 {letter-spacing: -0.01em;}
    .fc-banner {
        border-radius: 10px; padding: 0.7rem 1rem; margin-bottom: 1rem;
        background: rgba(255, 176, 32, 0.12); border: 1px solid rgba(255, 176, 32, 0.35);
        font-size: 0.92rem;
    }
    .fc-caption {opacity: 0.72; font-size: 0.85rem;}
    .fc-legend-swatch {
        display: inline-block; width: 14px; height: 14px; border-radius: 3px;
        margin-right: 4px; vertical-align: middle;
    }
    .fc-nodata {opacity: 0.55; font-style: italic;}
    </style>
    """,
    unsafe_allow_html=True,
)

ss = state.init_state()


def _run_and_store(concept_text: str) -> None:
    data, source, message = api_client.analyze_concept(concept_text, ss["center"], ss["radius_mi"])
    state.set_analysis(ss, data, source, message)
    ss["concept_text"] = concept_text


def _rerun_with_profile(profile: dict) -> None:
    data, source, message = api_client.get_analysis(profile, ss["center"], ss["radius_mi"])
    state.set_analysis(ss, data, source, message)


st.title("🍜 Forkcast")
st.caption("Where should this restaurant concept open in Pittsburgh?")

# ---------------------------------------------------------------------------
# 1. Concept input
# ---------------------------------------------------------------------------
with st.container(border=True):
    st.subheader("1 · Concept")
    concept_box_col, run_col = st.columns([5, 1])
    concept_text = concept_box_col.text_input(
        "Describe the restaurant concept",
        value=ss["concept_text"],
        placeholder="e.g. Cheap Korean street food under $15 for college students, open late.",
        label_visibility="collapsed",
    )
    if run_col.button("Analyze", type="primary", use_container_width=True):
        with st.spinner("Parsing concept → scoring cells → merging zones…"):
            _run_and_store(concept_text)

    demo_cols = st.columns(len(state.DEMO_CONCEPTS))
    for col, demo_text in zip(demo_cols, state.DEMO_CONCEPTS):
        short = demo_text.split(",")[0].split(".")[0]
        if col.button(short, key=f"demo_{short}", use_container_width=True):
            with st.spinner("Parsing concept → scoring cells → merging zones…"):
                _run_and_store(demo_text)

# First load: run the first demo concept automatically so the app is never empty,
# and so the fixture fallback is visible immediately when the API is down.
if ss["analysis"] is None:
    with st.spinner("Loading…"):
        _run_and_store(state.DEMO_CONCEPTS[0])

analysis = ss["analysis"]
profile = ss["profile"] or {}

if ss["analysis_source"] == "fixture":
    st.markdown(f"<div class='fc-banner'>🧪 {ss['analysis_message']}</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 2. Editable profile chips + refine bar
# ---------------------------------------------------------------------------
with st.container(border=True):
    st.subheader("2 · Concept profile")
    info_col, edit_col = st.columns([1, 2])

    with info_col:
        st.markdown(f"**{profile.get('concept_name', '—')}**")
        st.caption(
            f"{profile.get('service_format', '—')} · price tier {profile.get('price_tier', '—')}/4 "
            f"· avg ticket ${profile.get('avg_ticket_usd', '—')} · catchment {profile.get('catchment', '—')}"
        )
        weights = analysis.get("weights", {}) if analysis else {}
        st.caption("Sub-score weights (backend-validated):")
        st.dataframe(
            {SUBSCORE_LABELS[k]: [weights.get(k)] for k in SUBSCORE_KEYS if k in weights},
            hide_index=True,
            use_container_width=True,
        )
        st.markdown(f"<span class='fc-caption'>{competitor_caveat()}</span>", unsafe_allow_html=True)

    with edit_col:
        with st.form("profile_form"):
            cuisines_text = st.text_input(
                "Cuisines (comma-separated)", value=", ".join(profile.get("cuisines", []))
            )
            price_tier = st.select_slider(
                "Price tier", options=[1, 2, 3, 4], value=profile.get("price_tier", 2),
                format_func=lambda t: "$" * t,
            )
            st.markdown("**Dayparts**")
            daypart_cols = st.columns(len(DAYPART_KEYS))
            dayparts = {}
            for col, key in zip(daypart_cols, DAYPART_KEYS):
                dayparts[key] = col.slider(
                    key.replace("_", " ").title(), 0.0, 1.0,
                    float(profile.get("dayparts", {}).get(key, 0.0)), 0.05,
                    key=f"daypart_{key}",
                )
            with st.expander("Importance sliders"):
                importance_cols = st.columns(3)
                importances = {}
                for i, key in enumerate(IMPORTANCE_KEYS):
                    label = key.replace("_importance", "").replace("_", " ").title()
                    importances[key] = importance_cols[i % 3].slider(
                        label, 0.0, 1.0, float(profile.get(key, 0.5)), 0.05, key=f"imp_{key}",
                    )
            submitted = st.form_submit_button("Apply edits & re-run", use_container_width=True)
            if submitted and profile:
                edits = {
                    "cuisines": [c.strip() for c in cuisines_text.split(",") if c.strip()],
                    "price_tier": price_tier,
                    "dayparts": dayparts,
                    **importances,
                }
                with st.spinner("Re-scoring with edited profile…"):
                    _rerun_with_profile({**profile, **edits})
                st.rerun()

    st.divider()
    refine_col, refine_btn_col = st.columns([5, 1])
    instruction = refine_col.text_input(
        "Refine in plain language", placeholder="e.g. make it premium", key="refine_instruction",
        label_visibility="collapsed",
    )
    if refine_btn_col.button("Refine", use_container_width=True) and profile:
        try:
            resp = api_client.refine_concept(profile, instruction)
            new_profile, diff_lines = apply_refine_response(profile, resp)
            ss["last_refine_diff"] = diff_lines
            with st.spinner("Re-scoring with refined profile…"):
                _rerun_with_profile(new_profile)
            st.rerun()
        except api_client.ApiUnavailable as e:
            st.warning(f"Refine needs a running API ({e}). {api_client.START_HINT}")

    if ss["last_refine_diff"]:
        st.markdown("**What changed:**")
        for line in ss["last_refine_diff"]:
            st.markdown(f"- {line}")

# ---------------------------------------------------------------------------
# 3. Center & radius
# ---------------------------------------------------------------------------
with st.container(border=True):
    st.subheader("3 · Search area")
    lat_col, lng_col, radius_col = st.columns(3)
    ss["center"]["lat"] = lat_col.number_input(
        "Center latitude", value=ss["center"]["lat"], format="%.5f"
    )
    ss["center"]["lng"] = lng_col.number_input(
        "Center longitude", value=ss["center"]["lng"], format="%.5f"
    )
    ss["radius_mi"] = radius_col.slider("Radius (miles)", 0.5, 10.0, ss["radius_mi"], 0.5)

# ---------------------------------------------------------------------------
# 4. Hex map
# ---------------------------------------------------------------------------
tab_forward, tab_reverse = st.tabs(["Forward mode", "Reverse mode"])

with tab_forward:
    if analysis:
        st.subheader("4 · Opportunity map")
        layer_label = st.selectbox("Color by", list(state.LAYER_OPTIONS.keys()))
        metric_key = state.LAYER_OPTIONS[layer_label]
        records = build_hex_records(analysis["cells"], metric_key)

        legend_html = " ".join(
            f"<span class='fc-legend-swatch' style='background: rgb({r},{g},{b});'></span>{v}"
            for v, (r, g, b, _a) in [
                (0, color_for_score(0)), (25, color_for_score(25)), (50, color_for_score(50)),
                (75, color_for_score(75)), (100, color_for_score(100)),
            ]
        )
        null_r, null_g, null_b, _ = color_for_score(None)
        st.markdown(
            f"<span class='fc-caption'>Poor {legend_html} Excellent &nbsp;·&nbsp; "
            f"<span class='fc-legend-swatch' style='background: rgb({null_r},{null_g},{null_b});'>"
            f"</span>no data</span>",
            unsafe_allow_html=True,
        )
        if metric_key == "K":
            st.caption("Cost is unmeasured today — rent data has not been collected yet.")
        if metric_key == "T":
            st.caption(traffic_provenance_note())

        layer = pdk.Layer(
            "H3HexagonLayer",
            records,
            get_hexagon="h3",
            get_fill_color="fill_color",
            get_line_color=[255, 255, 255, 30],
            line_width_min_pixels=1,
            pickable=True,
            filled=True,
            stroked=True,
            opacity=0.85,
        )
        view_state = pdk.ViewState(
            latitude=ss["center"]["lat"], longitude=ss["center"]["lng"], zoom=12
        )
        tooltip = {
            "html": (
                "<b>{total_display}</b> total<br/>"
                "Demand {D_display} · Competition {C_display} · Traffic {T_display}<br/>"
                "Access {A_display} · Spending {S_spend_display} · "
                "Cost {K_display} · Supply {Sup_display}"
            ),
            "style": {"backgroundColor": "#1f2430", "color": "white", "fontSize": "0.8rem"},
        }
        st.pydeck_chart(
            pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip=tooltip, map_style=None)
        )

        # -----------------------------------------------------------------
        # 5. Zone leaderboard
        # -----------------------------------------------------------------
        st.subheader("5 · Zone leaderboard")
        ranked = rank_zones(analysis["zones"])
        for rank, zone in enumerate(ranked, start=1):
            with st.container(border=True):
                head = st.columns([0.6, 3, 1, 1, 1])
                head[0].markdown(f"### #{rank}")
                head[1].markdown(f"**{zone['name']}**")
                head[2].metric("Total", f"{zone['total']:.0f}")
                head[3].metric("Confidence", f"{zone['confidence']:.0%}")
                head[4].markdown("🟢 Gap" if zone.get("gap_flag") else "—")

                with st.expander("Sub-scores, drivers, competitors, anchors, Why-Here"):
                    sub_cols = st.columns(len(SUBSCORE_KEYS))
                    for col, key in zip(sub_cols, SUBSCORE_KEYS):
                        val = zone["subscores"].get(key)
                        frac = score_bar_fraction(val)
                        label = SUBSCORE_LABELS[key] + (" *" if key in PROXY_SUBSCORES else "")
                        col.caption(label)
                        if frac is None:
                            col.markdown("<span class='fc-nodata'>no data</span>", unsafe_allow_html=True)
                        else:
                            col.progress(frac, text=format_score(val))
                    st.caption("* " + traffic_provenance_note())

                    if zone["drivers"]:
                        st.markdown("**Drivers:** " + "; ".join(zone["drivers"]))
                    if zone["risks"]:
                        st.markdown("**Risks:** " + "; ".join(zone["risks"]))
                    st.markdown(f"**Rent:** {format_rent(zone['est_rent_psf_yr'], zone['rent_confidence'])}")

                    comp_col, anchor_col = st.columns(2)
                    with comp_col:
                        st.markdown("**Direct competitors**")
                        if zone["competitors_direct"]:
                            for c in zone["competitors_direct"]:
                                st.markdown(f"- {c['name']} — {c['distance_m']:.0f} m, sim {c['similarity']:.2f}")
                        else:
                            st.markdown("_None found nearby._")
                        st.markdown("**Indirect competitors**")
                        if zone["competitors_indirect"]:
                            for c in zone["competitors_indirect"]:
                                st.markdown(f"- {c['name']} — {c['distance_m']:.0f} m, sim {c['similarity']:.2f}")
                        else:
                            st.markdown("_None found nearby._")
                        st.caption(competitor_caveat())
                    with anchor_col:
                        st.markdown("**Anchors**")
                        if zone["anchors"]:
                            for a in zone["anchors"]:
                                st.markdown(f"- {a['name']} ({a['type']}) — {a['distance_m']:.0f} m")
                        else:
                            st.markdown("_None nearby._")

                    st.divider()
                    st.markdown("**Why here?**")
                    if st.button("Explain this zone", key=f"why_{zone['zone_id']}"):
                        with st.spinner("Asking the explainer…"):
                            resp, source = api_client.explain_or_fallback(profile, zone)
                            ss["why_here"][zone["zone_id"]] = (resp, source)
                    cached = ss["why_here"].get(zone["zone_id"])
                    if cached:
                        resp, source = cached
                        if source == "fallback":
                            st.caption("Offline fallback — no LLM narration available.")
                        st.markdown(resp.get("text", str(resp)))
    else:
        st.info("Enter a concept above and click Analyze to see the opportunity map.")

with tab_reverse:
    st.subheader("Reverse mode — what's this storefront missing?")
    st.caption("Drop a point; the engine scores ~100 concept archetypes against it and returns the top 8.")
    r_lat_col, r_lng_col, r_sqft_col = st.columns(3)
    r_lat = r_lat_col.number_input("Latitude", value=ss["center"]["lat"], format="%.5f", key="rev_lat")
    r_lng = r_lng_col.number_input("Longitude", value=ss["center"]["lng"], format="%.5f", key="rev_lng")
    r_sqft = r_sqft_col.number_input("Storefront sqft (optional)", min_value=0, value=0, step=50)

    if st.button("Find top concepts", type="primary"):
        try:
            with st.spinner("Scoring concept archetypes against this point…"):
                ss["reverse_result"] = api_client.reverse_lookup(r_lat, r_lng, sqft=r_sqft or None)
                ss["reverse_error"] = None
        except api_client.ApiUnavailable as e:
            ss["reverse_result"] = None
            ss["reverse_error"] = str(e)

    if ss.get("reverse_error"):
        st.markdown(
            f"<div class='fc-banner'>Reverse mode needs a running API — the fixture has no "
            f"reverse-mode data to fall back to ({ss['reverse_error']}). {api_client.START_HINT}</div>",
            unsafe_allow_html=True,
        )
    result = ss.get("reverse_result")
    if result:
        concepts = result.get("concepts", result if isinstance(result, list) else [])
        for i, c in enumerate(concepts[:8], start=1):
            with st.container(border=True):
                st.markdown(f"**#{i} {c.get('concept_name', c.get('name', 'Concept'))}**")
                total = c.get("total")
                st.caption(f"Score: {format_score(total)}" if total is not None else "Score: no data")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
try:
    meta = api_client.get_meta()
    rho = meta.get("backtest_rho")
    n = meta.get("n")
except api_client.ApiUnavailable:
    rho = analysis.get("backtest_rho") if analysis else None
    n = None
st.caption(
    f"{format_backtest_rho(rho, n)} · Scoring estimates only — not financial advice."
)
