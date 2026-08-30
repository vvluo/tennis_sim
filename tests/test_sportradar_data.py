"""Fixture tests for the Sportradar -> Match Charting Project flattening.

Built against the documented v3 response shape, so the mapping can be checked
without spending API calls. Numbers are internally consistent the way a real
match is: first_in + second_in + dfs == serve_pts, and first_won + second_won
== service_points_won.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import math

import pandas as pd

from sportradar_data import (
    check_groundstroke_identity,
    coverage_report,
    flatten_summaries,
)

# Swiatek: 70 serve pts = 44 first in + 22 second in + 4 double faults
#          45 service pts won = 33 off first serve + 12 off second
A_STATS = {
    "aces": 5, "double_faults": 4,
    "first_serve_successful": 44, "first_serve_points_won": 33,
    "second_serve_successful": 22, "second_serve_points_won": 12,
    "service_points_won": 45, "service_points_lost": 25,
    "total_breakpoints": 9, "breakpoints_won": 5,   # as returner
    "points_won": 77,
    "groundstroke_winners": 18, "forehand_winners": 13, "backhand_winners": 8,  # wings = 18 gs + 3 volley
    "volley_winners": 3, "drop_shot_winners": 2, "lob_winners": 1,
    "overhead_stroke_winners": 1, "return_winners": 4,
    "groundstroke_unforced_errors": 20,
    "forehand_unforced_errors": 13, "backhand_unforced_errors": 9,  # wings = 20 ue + 2 volley
    "volley_unforced_errors": 2, "drop_shot_unforced_errors": 1,
    "lob_unforced_errors": 0, "overhead_stroke_unforced_errors": 1,
}

# Opponent has serve stats only -- no enhanced shot-level coverage.
B_STATS = {
    "aces": 2, "double_faults": 5,
    "first_serve_successful": 40, "first_serve_points_won": 28,
    "second_serve_successful": 25, "second_serve_points_won": 10,
    "service_points_won": 38, "service_points_lost": 32,
    "total_breakpoints": 4, "breakpoints_won": 2,
    "points_won": 63,
}


def _match(event_id, gender, comp_type, status, names, stats, start="2026-05-14T11:00:00+00:00"):
    ids = [f"sr:competitor:{event_id}{n}" for n in (1, 2)]
    return {
        "sport_event": {
            "id": f"sr:sport_event:{event_id}",
            "start_time": start,
            "sport_event_context": {
                "competition": {"id": "sr:competition:2553", "name": "WTA Rome",
                                "gender": gender, "type": comp_type,
                                "level": "wta_1000", "surface": "red_clay"},
                "round": {"name": "quarterfinal"},
            },
            "competitors": [
                {"id": ids[0], "name": names[0], "qualifier": "home"},
                {"id": ids[1], "name": names[1], "qualifier": "away"},
            ],
        },
        "sport_event_status": {
            "status": status, "match_status": "ended",
            "home_score": 2, "away_score": 0, "winner_id": ids[0],
            "period_scores": [
                {"number": 1, "type": "set", "home_score": 6, "away_score": 4},
                {"number": 2, "type": "set", "home_score": 6, "away_score": 3},
            ],
        },
        "statistics": {
            "totals": {
                "competitors": [
                    {"id": ids[0], "name": names[0], "statistics": stats[0]},
                    {"id": ids[1], "name": names[1], "statistics": stats[1]},
                ]
            }
        },
    }


SINGLES = _match("111", "women", "singles", "closed",
                 ["Swiatek, Iga", "Anisimova, Amanda"], [A_STATS, B_STATS])
DOUBLES = _match("222", "women", "doubles", "closed",
                 ["Dabrowski, Gabriela", "Routliffe, Erin"], [A_STATS, B_STATS])
LIVE = _match("333", "women", "singles", "live",
              ["Gauff, Coco", "Sabalenka, Aryna"], [A_STATS, B_STATS])

df = flatten_summaries([SINGLES, DOUBLES, LIVE])

# --- shape -----------------------------------------------------------------
assert len(df) == 2, f"expected the one completed singles match, got {len(df)} rows"
assert set(df["player"]) == {"Iga Swiatek", "Amanda Anisimova"}, "name flip failed"

a = df[df["player"] == "Iga Swiatek"].iloc[0]
b = df[df["player"] == "Amanda Anisimova"].iloc[0]

# --- serve -----------------------------------------------------------------
assert a["serve_pts"] == 70
assert a["second_in"] == 22 + 4, "second_in counts points played, dfs included"
assert a["first_in"] + a["second_in"] == a["serve_pts"], "serve split must close"
assert a["serve_gap"] == 0
assert a["first_won"] + a["second_won"] == 45, "serve points won must close"

# --- break points come off the opponent's returner-side counters ------------
assert a["bk_pts"] == 4 and a["bp_saved"] == 2, "A faced B's 4 bps, saved 2"
assert b["bk_pts"] == 9 and b["bp_saved"] == 4, "B faced A's 9 bps, saved 4"

# --- return ----------------------------------------------------------------
assert a["return_pts"] == b["serve_pts"] == 70
assert a["return_pts_won"] == 32, "A won the 32 points B lost on serve"

# --- rally: rollup used once, other categories added, no double count -------
assert a["winners"] == 18 + 3 + 2 + 1 + 1 + 4 + 5, f"winners wrong: {a['winners']}"  # + 5 aces
assert a["unforced"] == 20 + 2 + 1 + 0 + 1 + 4, f"unforced wrong: {a['unforced']}"  # + 4 double faults
assert math.isnan(b["winners"]) and math.isnan(b["unforced"]), \
    "uncollected shot stats must be NaN, never 0"

# --- rates the notebook computes -------------------------------------------
assert abs(a["aces"] / a["serve_pts"] - 0.0714) < 1e-3
assert abs(a["first_won"] / a["first_in"] - 0.75) < 1e-9
assert abs(a["bp_saved"] / a["bk_pts"] - 0.5) < 1e-9
assert abs(a["return_pts_won"] / a["return_pts"] - 0.4571) < 1e-3

# --- match_id still parses the way the notebook expects ---------------------
def players_from_match_id(match_id):
    x, y = match_id.split("-")[-2:]
    return x.replace("_", " "), y.replace("_", " ")

assert players_from_match_id(a["match_id"]) == ("Iga Swiatek", "Amanda Anisimova")
assert a["match_date"] == 20260514
assert df["match_date"].dtype.kind == "i", "match_date must stay integer for the date filter"

# --- fall back to forehand+backhand when the rollup is absent ---------------
no_rollup = dict(A_STATS)
del no_rollup["groundstroke_winners"]
del no_rollup["groundstroke_unforced_errors"]
fallback = flatten_summaries(
    [_match("444", "women", "singles", "closed",
            ["Rybakina, Elena", "Keys, Madison"], [no_rollup, B_STATS])]
)
# wings already include volleys, so volley_winners must NOT be added again
assert fallback.iloc[0]["winners"] == 13 + 8 + 2 + 1 + 1 + 4 + 5
assert fallback.iloc[0]["unforced"] == 13 + 9 + 1 + 0 + 1 + 4

# --- diagnostics -----------------------------------------------------------
identity = check_groundstroke_identity([SINGLES])
assert set(identity["field"]) == {"groundstroke_winners", "groundstroke_unforced_errors"}

coverage = coverage_report(df)
assert coverage.loc["serve_pts", "pct_present"] == 100.0
assert coverage.loc["winners", "pct_present"] == 50.0

print("all fixture checks passed")
print(coverage.to_string())
