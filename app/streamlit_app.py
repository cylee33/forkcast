"""Forkcast — interactive Streamlit interface.

Run with: `streamlit run app/streamlit_app.py`

Calls the FastAPI service over HTTP (`FORKCAST_API`, default `http://localhost:8000`) —
never imports `api/scoring` or `api/services` directly, so the API is genuinely
exercised. Falls back to the committed fixture (`data/fixtures/recommend_sample.json`)
whenever the service is unreachable, so the app runs standalone. See `app/api_client.py`
for the HTTP + fallback logic and `app/formatting.py` for the pure rendering helpers.

Layout: a command bar on top, the opportunity grid as the hero, zones on the left and
the selected zone's detail on the right. Profile editing, the search area and the
refine bar live in the sidebar so the map keeps the width.
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
    build_grid_records,
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

GROUND = "#0E1420"
PANEL = "#151D2B"
LINE = "#243044"
INK = "#E6ECF5"
MUTED = "#8A97AB"
AMBER = "#FFD166"
TEAL = "#2EC4B6"

st.set_page_config(page_title="Forkcast", page_icon="▦", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    f"""
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
    html, body, [class*="css"], .stApp, .stMarkdown, .stButton, .stTextInput, .stSelectbox {{
        font-family: 'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif;
        font-variant-numeric: tabular-nums;
    }}
    .stApp {{ background: {GROUND}; }}
    header[data-testid="stHeader"] {{ background: transparent; }}
    .block-container {{ padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1440px; }}
    section[data-testid="stSidebar"] {{ background: {PANEL}; border-right: 1px solid {LINE}; }}
    section[data-testid="stSidebar"] .block-container {{ padding-top: 1.4rem; }}
    h1, h2, h3 {{ letter-spacing: -0.015em; font-weight: 600; }}
    h3 {{ font-size: 1.02rem; color: {INK}; margin-bottom: 0.3rem; }}
    hr {{ border-color: {LINE}; }}

    .fc-wordmark {{ font-size: 1.55rem; font-weight: 600; letter-spacing: -0.03em; line-height: 1; color: {INK}; }}
    .fc-wordmark span {{ display:inline-block; width: 0.55em; height: 0.55em; background: {AMBER}; margin-right: 0.35em; vertical-align: -0.02em; }}
    .fc-tagline {{ color: {MUTED}; font-size: 0.86rem; margin-top: 0.2rem; }}

    .fc-banner {{ padding: 0.55rem 0.9rem; margin: 0.4rem 0 0.8rem; background: rgba(255, 209, 102, 0.08);
                  border-left: 3px solid {AMBER}; font-size: 0.9rem; color: {INK}; }}
    .fc-caption {{ color: {MUTED}; font-size: 0.82rem; }}
    .fc-nodata {{ color: {MUTED}; font-style: italic; }}
    .fc-swatch {{ display:inline-block; width: 22px; height: 10px; vertical-align: middle; }}

    .fc-zone {{ display:grid; grid-template-columns: 2.2rem 1fr 3.2rem 6.5rem; gap: 0.6rem; align-items: center;
                padding: 0.5rem 0.6rem; border-bottom: 1px solid {LINE}; }}
    .fc-zone.sel {{ background: rgba(46, 196, 182, 0.09); border-left: 3px solid {TEAL}; padding-left: calc(0.6rem - 3px); }}
    .fc-zone .rank {{ color: {MUTED}; font-size: 0.85rem; }}
    .fc-zone .name {{ color: {INK}; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .fc-zone .total {{ color: {INK}; font-weight: 600; font-size: 1.05rem; text-align: right; }}
    .fc-track {{ height: 6px; background: {LINE}; }}
    .fc-fill {{ height: 6px; background: linear-gradient(90deg, {TEAL}, {AMBER}); }}

    .fc-big {{ font-size: 2.6rem; font-weight: 600; line-height: 1; color: {INK}; letter-spacing: -0.03em; }}
    .fc-big small {{ font-size: 0.85rem; font-weight: 400; color: {MUTED}; margin-left: 0.4rem; letter-spacing: 0; }}
    .fc-row {{ display:grid; grid-template-columns: 6.2rem 1fr 3rem; gap: 0.7rem; align-items:center; padding: 0.28rem 0; }}
    .fc-row .lbl {{ color: {MUTED}; font-size: 0.86rem; }}
    .fc-row .val {{ color: {INK}; text-align: right; font-size: 0.9rem; }}
    .fc-gap {{ display:inline-block; padding: 0.1rem 0.45rem; border: 1px solid {TEAL}; color: {TEAL}; font-size: 0.72rem; }}

    div[data-testid="stTabs"] button {{ font-weight: 500; }}
    .stButton > button {{ border-radius: 2px; }}
    div[data-testid="stTextInput"] input {{ border-radius: 2px; background: {PANEL}; }}
    </style>
    """,
    unsafe_allow_html=True,
)

ss = state.init_state()


def _run_and_store(concept_text: str) -> None:
    data, source, message = api_client.analyze_concept(concept_text, ss["center"], ss["radius_mi"])
    state.set_analysis(ss, data, source, message)
    ss["concept_text"] = concept_text
    ss["selected_zone_id"] = None


def _rerun_with_profile(profile: dict) -> None:
    data, source, message = api_client.get_analysis(profile, ss["center"], ss["radius_mi"])
    state.set_analysis(ss, data, source, message)
    ss["selected_zone_id"] = None


def _bar(value: float | None) -> str:
    frac = score_bar_fraction(value)
    if frac is None:
        return "<span class='fc-nodata'>no data</span>"
    return f"<div class='fc-track'><div class='fc-fill' style='width:{frac * 100:.0f}%'></div></div>"


# ---------------------------------------------------------------------------
# Command bar
# ---------------------------------------------------------------------------
brand_col, input_col, run_col = st.columns([1.3, 5, 1])
with brand_col:
    st.markdown("<div class='fc-wordmark'><span></span>Forkcast</div>", unsafe_allow_html=True)
    st.markdown("<div class='fc-tagline'>Where a restaurant concept should open in Pittsburgh</div>", unsafe_allow_html=True)
concept_text = input_col.text_input(
    "Concept", value=ss["concept_text"], label_visibility="collapsed",
    placeholder="Describe the concept — cuisine, price, who it's for, when it's busy",
)
run_clicked = run_col.button("Analyze", type="primary", use_container_width=True)
if run_clicked:
    with st.spinner("Scoring 18,275 cells"):
        _run_and_store(concept_text)

chip_cols = st.columns([1.3, 1.6, 1.6, 1.6, 1.3])
for col, demo_text in zip(chip_cols[1:4], state.DEMO_CONCEPTS):
    short = demo_text.split(",")[0].split(".")[0]
    if col.button(short, key=f"demo_{short}", use_container_width=True):
        with st.spinner("Scoring 18,275 cells"):
            _run_and_store(demo_text)

if ss["analysis"] is None:
    with st.spinner("Loading"):
        _run_and_store(state.DEMO_CONCEPTS[0])

analysis = ss["analysis"]
profile = ss["profile"] or {}

if ss["analysis_source"] == "fixture":
    st.markdown(f"<div class='fc-banner'>{ss['analysis_message']}</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar — profile, search area, refine
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Concept profile")
    st.markdown(f"**{profile.get('concept_name', '—')}**")
    st.markdown(
        f"<span class='fc-caption'>{profile.get('service_format', '—')}, tier "
        f"{'$' * int(profile.get('price_tier', 0) or 0) or '—'}, about ${profile.get('avg_ticket_usd', '—')} a head, "
        f"{profile.get('catchment', '—')} catchment</span>",
        unsafe_allow_html=True,
    )
    with st.form("profile_form", border=False):
        cuisines_text = st.text_input("Cuisines", value=", ".join(profile.get("cuisines", [])))
        price_tier = st.select_slider(
            "Price tier", options=[1, 2, 3, 4], value=int(profile.get("price_tier", 2) or 2),
            format_func=lambda t: "$" * t,
        )
        st.markdown("<span class='fc-caption'>Dayparts</span>", unsafe_allow_html=True)
        dayparts = {}
        for key in DAYPART_KEYS:
            dayparts[key] = st.slider(
                key.replace("_", " "), 0.0, 1.0,
                float(profile.get("dayparts", {}).get(key, 0.0)), 0.05, key=f"daypart_{key}",
            )
        with st.expander("What matters"):
            importances = {}
            for key in IMPORTANCE_KEYS:
                importances[key] = st.slider(
                    key.replace("_importance", "").replace("_", " "), 0.0, 1.0,
                    float(profile.get(key, 0.5)), 0.05, key=f"imp_{key}",
                )
        if st.form_submit_button("Apply and re-score", use_container_width=True) and profile:
            edits = {
                "cuisines": [c.strip() for c in cuisines_text.split(",") if c.strip()],
                "price_tier": price_tier,
                "dayparts": dayparts,
                **importances,
            }
            with st.spinner("Re-scoring"):
                _rerun_with_profile({**profile, **edits})
            st.rerun()

    st.markdown("### Refine")
    instruction = st.text_input("Refine", placeholder="make it premium", key="refine_instruction", label_visibility="collapsed")
    if st.button("Refine and re-score", use_container_width=True) and profile and instruction:
        try:
            resp = api_client.refine_concept(profile, instruction)
            new_profile, diff_lines = apply_refine_response(profile, resp)
            ss["last_refine_diff"] = diff_lines
            with st.spinner("Re-scoring"):
                _rerun_with_profile(new_profile)
            st.rerun()
        except api_client.ApiUnavailable as e:
            st.warning(f"Refine needs the API running ({e}). {api_client.START_HINT}")
    if ss["last_refine_diff"]:
        st.markdown("<span class='fc-caption'>Changed</span>", unsafe_allow_html=True)
        for line in ss["last_refine_diff"]:
            st.markdown(f"<span class='fc-caption'>{line}</span>", unsafe_allow_html=True)

    st.markdown("### Search area")
    ss["center"]["lat"] = st.number_input("Latitude", value=ss["center"]["lat"], format="%.5f")
    ss["center"]["lng"] = st.number_input("Longitude", value=ss["center"]["lng"], format="%.5f")
    ss["radius_mi"] = st.slider("Radius, miles", 0.5, 10.0, ss["radius_mi"], 0.5)

    weights = analysis.get("weights", {}) if analysis else {}
    if weights:
        st.markdown("### Weights")
        st.markdown("<span class='fc-caption'>Proposed by the parser, validated by the engine. Cost is 0 until rent data exists.</span>", unsafe_allow_html=True)
        for k in SUBSCORE_KEYS:
            if k in weights:
                st.markdown(
                    f"<div class='fc-row'><span class='lbl'>{SUBSCORE_LABELS[k]}</span>"
                    f"<div class='fc-track'><div class='fc-fill' style='width:{weights[k] * 100:.0f}%'></div></div>"
                    f"<span class='val'>{weights[k]:.2f}</span></div>",
                    unsafe_allow_html=True,
                )

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
tab_forward, tab_reverse = st.tabs(["Find a location", "What fits here"])

with tab_forward:
    if analysis:
        ctl_col, legend_col = st.columns([1.2, 4])
        layer_label = ctl_col.selectbox("Color by", list(state.LAYER_OPTIONS.keys()), label_visibility="collapsed")
        metric_key = state.LAYER_OPTIONS[layer_label]
        records = build_grid_records(analysis["cells"], metric_key)

        swatches = "".join(
            f"<span class='fc-swatch' style='background: rgb({r},{g},{b});'></span>"
            for r, g, b, _a in (color_for_score(v) for v in (0, 20, 40, 60, 80, 100))
        )
        nr, ng, nb, _ = color_for_score(None)
        note = ""
        if metric_key == "K":
            note = " &nbsp; Cost is unmeasured — no rent data has been collected."
        elif metric_key == "T":
            note = f" &nbsp; {traffic_provenance_note()}"
        legend_col.markdown(
            f"<div style='padding-top:0.55rem' class='fc-caption'>Weak {swatches} Strong &nbsp;&nbsp; "
            f"<span class='fc-swatch' style='background: rgb({nr},{ng},{nb});'></span> no data{note}</div>",
            unsafe_allow_html=True,
        )

        layer = pdk.Layer(
            "PolygonLayer",
            records,
            get_polygon="polygon",
            get_fill_color="fill_color",
            get_line_color=[14, 20, 32, 160],
            line_width_min_pixels=1,
            filled=True,
            stroked=True,
            extruded=False,
            pickable=True,
            opacity=0.92,
        )
        view_state = pdk.ViewState(latitude=ss["center"]["lat"], longitude=ss["center"]["lng"], zoom=12.2)
        tooltip = {
            "html": (
                "<div style='font-size:1.1rem;font-weight:600'>{total_display}</div>"
                "Demand {D_display} &nbsp; Competition {C_display} &nbsp; Traffic {T_display}<br/>"
                "Access {A_display} &nbsp; Spending {S_spend_display} &nbsp; Cost {K_display} &nbsp; Supply {Sup_display}"
            ),
            "style": {"backgroundColor": PANEL, "color": INK, "fontSize": "0.78rem", "border": f"1px solid {LINE}"},
        }
        st.pydeck_chart(
            pdk.Deck(
                layers=[layer], initial_view_state=view_state, tooltip=tooltip,
                map_provider="carto", map_style="dark",
            ),
            use_container_width=True,
        )

        ranked = rank_zones(analysis["zones"])
        if ss.get("selected_zone_id") is None and ranked:
            ss["selected_zone_id"] = ranked[0]["zone_id"]
        selected = next((z for z in ranked if z["zone_id"] == ss.get("selected_zone_id")), ranked[0] if ranked else None)

        zones_col, detail_col = st.columns([1.15, 1.7], gap="large")

        with zones_col:
            st.markdown("### Zones")
            for rank, zone in enumerate(ranked, start=1):
                is_sel = selected is not None and zone["zone_id"] == selected["zone_id"]
                st.markdown(
                    f"<div class='fc-zone{' sel' if is_sel else ''}'>"
                    f"<span class='rank'>{rank}</span>"
                    f"<span class='name'>{zone['name']}</span>"
                    f"<span class='total'>{zone['total']:.0f}</span>"
                    f"{_bar(zone['total'])}</div>",
                    unsafe_allow_html=True,
                )
                if st.button("Open", key=f"sel_{zone['zone_id']}", use_container_width=False):
                    ss["selected_zone_id"] = zone["zone_id"]
                    st.rerun()

        with detail_col:
            if selected:
                zone = selected
                st.markdown("### Zone detail")
                head_l, head_r = st.columns([2, 1])
                head_l.markdown(f"**{zone['name']}**" + ("&nbsp; <span class='fc-gap'>market gap</span>" if zone.get("gap_flag") else ""), unsafe_allow_html=True)
                head_l.markdown(
                    f"<div class='fc-big'>{zone['total']:.0f}<small>opportunity</small></div>", unsafe_allow_html=True
                )
                head_r.markdown(
                    f"<div class='fc-big' style='font-size:1.6rem'>{zone['confidence']:.0%}<small>confidence</small></div>",
                    unsafe_allow_html=True,
                )
                for key in SUBSCORE_KEYS:
                    val = zone["subscores"].get(key)
                    label = SUBSCORE_LABELS[key] + (" (proxy)" if key in PROXY_SUBSCORES else "")
                    st.markdown(
                        f"<div class='fc-row'><span class='lbl'>{label}</span>{_bar(val)}"
                        f"<span class='val'>{format_score(val)}</span></div>",
                        unsafe_allow_html=True,
                    )
                st.markdown(f"<span class='fc-caption'>{format_rent(zone['est_rent_psf_yr'], zone['rent_confidence'])}. {traffic_provenance_note()}</span>", unsafe_allow_html=True)

                if zone["drivers"] or zone["risks"]:
                    dr, rk = st.columns(2)
                    if zone["drivers"]:
                        dr.markdown("**Drivers**")
                        for d in zone["drivers"]:
                            dr.markdown(f"- {d}")
                    if zone["risks"]:
                        rk.markdown("**Risks**")
                        for r in zone["risks"]:
                            rk.markdown(f"- {r}")

                comp_col, anchor_col = st.columns(2)
                with comp_col:
                    st.markdown("**Competitors**")
                    comps = zone["competitors_direct"] + zone["competitors_indirect"]
                    if comps:
                        for c in comps[:6]:
                            st.markdown(f"<div class='fc-row' style='grid-template-columns:1fr 3.4rem 2.6rem'><span>{c['name']}</span><span class='val'>{c['distance_m']:.0f} m</span><span class='val'>{c['similarity']:.2f}</span></div>", unsafe_allow_html=True)
                    else:
                        st.markdown("<span class='fc-nodata'>none found nearby</span>", unsafe_allow_html=True)
                    st.markdown(f"<span class='fc-caption'>{competitor_caveat()}</span>", unsafe_allow_html=True)
                with anchor_col:
                    st.markdown("**Anchors**")
                    if zone["anchors"]:
                        for a in zone["anchors"]:
                            st.markdown(f"<div class='fc-row' style='grid-template-columns:1fr 3.4rem'><span>{a['name']} <span class='fc-caption'>{a['type']}</span></span><span class='val'>{a['distance_m']:.0f} m</span></div>", unsafe_allow_html=True)
                    else:
                        st.markdown("<span class='fc-nodata'>none nearby</span>", unsafe_allow_html=True)

                st.markdown("**Why here**")
                if st.button("Explain this zone", key=f"why_{zone['zone_id']}"):
                    with st.spinner("Writing the explanation from the computed numbers"):
                        resp, source = api_client.explain_or_fallback(profile, zone)
                        ss["why_here"][zone["zone_id"]] = (resp, source)
                cached = ss["why_here"].get(zone["zone_id"])
                if cached:
                    resp, source = cached
                    if source == "fallback":
                        st.markdown("<span class='fc-caption'>Generated from the computed numbers without the language model.</span>", unsafe_allow_html=True)
                    st.markdown(resp.get("text", str(resp)))
    else:
        st.info("Describe a concept above and press Analyze.")

with tab_reverse:
    st.markdown("### What would work at this address")
    st.markdown("<span class='fc-caption'>Scores every concept archetype against one point and returns the eight that fit best.</span>", unsafe_allow_html=True)
    r_lat_col, r_lng_col, r_sqft_col, r_btn = st.columns([1, 1, 1, 1])
    r_lat = r_lat_col.number_input("Latitude", value=ss["center"]["lat"], format="%.5f", key="rev_lat")
    r_lng = r_lng_col.number_input("Longitude", value=ss["center"]["lng"], format="%.5f", key="rev_lng")
    r_sqft = r_sqft_col.number_input("Storefront sqft", min_value=0, value=0, step=50)
    r_btn.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
    if r_btn.button("Find concepts", type="primary", use_container_width=True):
        try:
            with st.spinner("Scoring archetypes"):
                ss["reverse_result"] = api_client.reverse_lookup(r_lat, r_lng, sqft=r_sqft or None)
                ss["reverse_error"] = None
        except api_client.ApiUnavailable as e:
            ss["reverse_result"] = None
            ss["reverse_error"] = str(e)

    if ss.get("reverse_error"):
        st.markdown(
            f"<div class='fc-banner'>Reverse mode needs the API running — the fixture has no reverse data. "
            f"({ss['reverse_error']}) {api_client.START_HINT}</div>",
            unsafe_allow_html=True,
        )
    result = ss.get("reverse_result")
    if result:
        concepts = result.get("concepts", result if isinstance(result, list) else [])
        for i, c in enumerate(concepts[:8], start=1):
            total = c.get("total")
            st.markdown(
                f"<div class='fc-zone'><span class='rank'>{i}</span>"
                f"<span class='name'>{c.get('concept_name', c.get('name', 'Concept'))}</span>"
                f"<span class='total'>{format_score(total)}</span>{_bar(total)}</div>",
                unsafe_allow_html=True,
            )
            subs = c.get("subscores") or {}
            if subs:
                st.markdown(
                    "<span class='fc-caption'>" + " &nbsp; ".join(
                        f"{SUBSCORE_LABELS[k]} {format_score(subs.get(k))}" for k in SUBSCORE_KEYS if k in subs
                    ) + "</span>",
                    unsafe_allow_html=True,
                )

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
try:
    meta = api_client.get_meta()
    rho = meta.get("backtest_rho")
    n = meta.get("backtest_n", meta.get("n"))
except api_client.ApiUnavailable:
    rho = analysis.get("backtest_rho") if analysis else None
    n = None
st.markdown(
    f"<span class='fc-caption'>{format_backtest_rho(rho, n)} Scoring estimates only, not financial advice.</span>",
    unsafe_allow_html=True,
)
