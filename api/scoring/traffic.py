"""Traffic-fit sub-score T (§5.4): the concept's own daypart weights against each cell's
relative activity by daypart. `traffic_source` is "proxy" everywhere right now (Task 10) --
that is reflected in `confidence`, not here.
"""
import pandas as pd

DAYPART_TO_ACTIVITY = {
    "breakfast": "activity_morning", "lunch": "activity_lunch", "dinner": "activity_dinner",
    "late_night": "activity_late_night", "weekend": "activity_weekend",
}


def raw(profile, f: pd.DataFrame) -> pd.Series:
    out = pd.Series(0.0, index=f.index)
    for d, w in (profile.dayparts or {}).items():
        col = DAYPART_TO_ACTIVITY.get(d)
        if col and w > 0:
            out = out + w * f[col].fillna(0.0)
    return out
