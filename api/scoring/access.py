"""Access sub-score A (§5.4): a profile-weighted blend of pedestrian density, transit
service, parking supply and road visibility, each taken from cell_features' own
metro-wide percentile columns (comparable units already) before being weighted and
re-percentiled across the scored set. No dist_to_* column is used here, so the
"dist_to_*_pct is inverted" convention does not apply to this sub-score.
"""
import pandas as pd


def raw(profile, f: pd.DataFrame) -> pd.Series:
    return (
        profile.pedestrian_importance * f["walkable_poi_density_pct"].fillna(0.0)
        + profile.transit_importance * f["transit_daily_trips_pct"].fillna(0.0)
        + profile.parking_importance * f["parking_lots_pct"].fillna(0.0)
        + profile.visibility_importance * f["main_road_frontage_pct"].fillna(0.0)
    )
