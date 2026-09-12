"""Demand sub-score D (§5.2): a gravity catchment over nearby population, weighted by how
well the concept fits each source cell's likely customers and local spending profile,
decayed by travel time to the catchment's travel mode.

The proposal leaves r_d/w_d (resident/worker daypart weights) undefined for breakfast,
late_night and weekend -- only lunch (r=.3, w=1) and dinner (r=1, w=.2) are given verbatim.
The other three are an engineering judgment call: breakfast splits close to evenly between
commuting workers and residents; late_night and weekend are almost entirely resident-driven.
"""
import numpy as np
import pandas as pd

from api.scoring import geo, spending

DAYPART_RW = {
    "breakfast": (0.3, 0.5),
    "lunch": (0.3, 1.0),
    "dinner": (1.0, 0.2),
    "late_night": (0.7, 0.1),
    "weekend": (1.0, 0.3),
}

# archetype -> (percentile column(s) in cell_features, ConceptProfile importance field or
# None). None means the archetype carries importance 1.0 whenever the profile lists it --
# there's no dedicated importance field for tourists/young_adults in ConceptProfile.
ARCHETYPE_SIGNAL = {
    "students": (["pct_students_pct"], "university_importance"),
    "office_workers": (["workers_daytime_pct"], "office_importance"),
    "families": (["pct_families_with_kids_pct", "avg_hh_size_pct"], "family_importance"),
    "nightlife": (["anchor_bar_pct"], "nightlife_importance"),
    "tourists": (["anchor_hotel_pct", "anchor_attraction_pct"], None),
    "young_adults": (["pct_age_25_34_pct"], None),
}
FAMILIES_WEIGHTS = (0.7, 0.3)  # pct_families_with_kids, avg_hh_size


def customer_fit(profile, f: pd.DataFrame) -> pd.Series:
    archetypes = [a for a in profile.customer_archetypes if a in ARCHETYPE_SIGNAL]
    if not archetypes:
        return pd.Series(1.0, index=f.index)  # nothing stated: don't filter anyone out

    acc = pd.Series(0.0, index=f.index)
    total_w = 0.0
    for a in archetypes:
        cols, importance_field = ARCHETYPE_SIGNAL[a]
        importance = getattr(profile, importance_field) if importance_field else 1.0
        if a == "families":
            fk = f[cols[0]].fillna(0.0) / 100.0
            hs = f[cols[1]] / 100.0
            w0, w1 = FAMILIES_WEIGHTS
            # avg_hh_size is NULL on 71 cells (cell_features.md) -- fall back to
            # pct_families_with_kids alone there rather than propagate NaN into D.
            signal = pd.Series(np.where(hs.isna(), fk, w0 * fk + w1 * hs.fillna(0.0)), index=f.index)
        elif len(cols) == 1:
            signal = f[cols[0]].fillna(0.0) / 100.0
        else:
            signal = f[cols].fillna(0.0).mean(axis=1) / 100.0
        acc = acc + importance * signal
        total_w += importance
    if total_w <= 0:
        return pd.Series(1.0, index=f.index)
    return acc / total_w


def _pop_weighted(profile, f: pd.DataFrame) -> pd.Series:
    residents = f["pop_total"].fillna(0.0)
    workers = f["workers_daytime"].fillna(0.0)
    pop = pd.Series(0.0, index=f.index)
    for d, weight in (profile.dayparts or {}).items():
        if weight <= 0 or d not in DAYPART_RW:
            continue
        r, w = DAYPART_RW[d]
        pop = pop + weight * (residents * r + workers * w)
    return pop


def raw_demand(profile, features: pd.DataFrame, targets: list[str]) -> pd.Series:
    """Demand_i for each h3 in `targets`, gravity-summed over every cell in `features`
    (the exp(-t/tau) decay self-truncates -- far cells contribute ~0 -- so no separate
    radius cutoff is needed for correctness, and this stays a single vectorized matvec)."""
    pop = _pop_weighted(profile, features)
    fit = customer_fit(profile, features)
    sfit = spending.spend_fit(profile, features)
    source_value = (pop * fit * sfit).to_numpy()

    speed = geo.CATCHMENT_SPEED_KMH[profile.catchment]
    tau = profile.catchment_tau_min
    tlat = features.loc[targets, "lat"].to_numpy()[:, None]
    tlng = features.loc[targets, "lng"].to_numpy()[:, None]
    slat = features["lat"].to_numpy()[None, :]
    slng = features["lng"].to_numpy()[None, :]
    dist_km = geo.haversine_km(tlat, tlng, slat, slng)
    minutes = dist_km / speed * 60.0
    decay = np.exp(-minutes / tau)
    demand = decay @ source_value
    return pd.Series(demand, index=targets)
