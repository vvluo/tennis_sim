"""Sportradar Tennis v3 -> match-stats DataFrame.

Replaces the Match Charting Project CSVs as the data source for
historical_data_analysis.ipynb.  The flattened frame deliberately keeps the
Match Charting Project column names (serve_pts, first_in, bp_saved, ...) so
the parameter-tuning cells downstream need no changes.

Trial keys are metered (~1 query/second, ~1,000 calls/month), so every
response is cached to disk and the client refuses to exceed a per-session
request budget.  Re-running a notebook cell costs zero API calls.

Auth check (spends exactly one request):

    python sportradar_data.py --check
"""

from __future__ import annotations

import gzip
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

PROJECT_DIR = Path(__file__).resolve().parent
CACHE_DIR = PROJECT_DIR / "sportradar_cache"
KEY_FILE = PROJECT_DIR / ".sportradar_key"

BASE_URL = "https://api.sportradar.com/tennis/{access_level}/v3/{language}"


def load_api_key() -> str:
    """Key from $SPORTRADAR_API_KEY, else the untracked .sportradar_key file."""
    key = os.environ.get("SPORTRADAR_API_KEY")
    if key:
        return key.strip()
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip()
    raise RuntimeError(
        f"No API key. Set $SPORTRADAR_API_KEY or write it to {KEY_FILE}."
    )


class SportradarError(RuntimeError):
    pass


class BudgetExceeded(SportradarError):
    pass


class Client:
    """Rate-limited, disk-cached Sportradar Tennis v3 client.

    min_interval  seconds between live requests (trial tier allows ~1 QPS)
    budget        hard cap on live requests per Client, so a runaway loop
                  cannot burn the monthly quota.  Cache hits are free.
    """

    def __init__(
        self,
        api_key: str | None = None,
        access_level: str | None = None,
        language: str = "en",
        min_interval: float = 1.2,
        budget: int = 300,
        cache_dir: Path = CACHE_DIR,
    ):
        # Deferred, not resolved here: a cache-only client (budget 0) never
        # makes a request, so it must not demand a key. The site deploy runs
        # exactly that way -- it has no secret, and it is not allowed to spend.
        self._api_key = api_key
        # The access level is part of the URL, so a production key aimed at the
        # trial endpoint is rejected as an auth failure rather than a wrong-tier
        # one. $SPORTRADAR_ACCESS_LEVEL lets the tier follow the key.
        access_level = access_level or os.environ.get("SPORTRADAR_ACCESS_LEVEL", "trial")
        self.access_level = access_level
        self.base = BASE_URL.format(access_level=access_level, language=language)
        self.min_interval = min_interval
        # $SPORTRADAR_BUDGET is a ceiling over the whole process, not a default:
        # it has to beat an explicit budget or a caller that asks for 520 would
        # walk straight past the cap the scheduled job was started with.
        cap = os.environ.get("SPORTRADAR_BUDGET")
        self.budget = min(budget, int(cap)) if cap else budget
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.requests_made = 0
        self._last_call = 0.0
        self._session = requests.Session()
        self._session.headers.update(
            {"accept": "application/json"}
        )

    # --- transport ------------------------------------------------------
    def _cache_path(self, cache_key: str) -> Path:
        return self.cache_dir / f"{cache_key}.json.gz"

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    @property
    def api_key(self) -> str:
        """The key, resolved on demand. Reading this raises if none is set."""
        self._authorize()
        return self._api_key

    def _authorize(self) -> None:
        """Attach the key to the session, resolving it the first time."""
        if self._api_key is None:
            self._api_key = load_api_key()
        self._session.headers["x-api-key"] = self._api_key

    def get(self, path: str, params: dict | None = None, cache_key: str | None = None):
        """GET one feed, served from disk when already fetched."""
        if cache_key:
            cached = self._cache_path(cache_key)
            if cached.exists():
                with gzip.open(cached, "rt") as fh:
                    return json.load(fh)

        if self.requests_made >= self.budget:
            raise BudgetExceeded(
                f"Request budget of {self.budget} used up. Raise Client(budget=...) "
                "deliberately -- the trial quota is ~1,000 calls/month."
            )

        url = f"{self.base}/{path}"
        self._authorize()          # a live call is due, so the key is needed now
        for attempt in range(4):
            self._throttle()
            try:
                response = self._session.get(url, params=params, timeout=30)
            except requests.RequestException as exc:
                # Long backfills run for minutes; the far end drops the odd
                # connection. Retry rather than losing the whole pull.
                self.requests_made += 1
                if attempt == 3:
                    raise SportradarError(f"network error on {url}: {exc}") from exc
                time.sleep(2 ** attempt)
                continue
            self.requests_made += 1
            if response.status_code == 200:
                payload = response.json()
                if cache_key:
                    with gzip.open(self._cache_path(cache_key), "wt") as fh:
                        json.dump(payload, fh)
                return payload
            if response.status_code == 429:  # throttled -- back off and retry
                time.sleep(2 ** attempt)
                continue
            if response.status_code == 404:
                raise SportradarError(f"404 (no such feed / no data): {url}")
            if response.status_code in (401, 403):
                raise SportradarError(
                    f"{response.status_code} Authentication Error for {url}\n"
                    f"The key was rejected at access level {self.access_level!r}. "
                    "A production key aimed at the trial endpoint fails exactly "
                    "like a bad key -- set $SPORTRADAR_ACCESS_LEVEL to match it."
                )
            raise SportradarError(f"{response.status_code} for {url}: {response.text[:200]}")
        raise SportradarError(f"Rate limited repeatedly on {url}")

    # --- feeds ----------------------------------------------------------
    def daily_summaries(self, day: date) -> list[dict]:
        """Every match on one calendar day, across all competitions."""
        day_str = day.isoformat()
        out, start = [], 0
        while True:
            page = self.get(
                f"schedules/{day_str}/summaries.json",
                params={"start": start, "limit": 200},
                cache_key=f"daily_{day_str}_{start}",
            )
            chunk = page.get("summaries", [])
            out.extend(chunk)
            if len(chunk) < 200:
                return out
            start += 200

    def season_summaries(self, season_id: str) -> list[dict]:
        """Every match of one tournament season -- far cheaper than day-by-day."""
        safe = season_id.replace(":", "_")
        out, start = [], 0
        while True:
            page = self.get(
                f"seasons/{season_id}/summaries.json",
                params={"start": start, "limit": 200},
                cache_key=f"season_{safe}_{start}",
            )
            chunk = page.get("summaries", [])
            out.extend(chunk)
            if len(chunk) < 200:
                return out
            start += 200

    def competitions(self) -> list[dict]:
        return self.get("competitions.json", cache_key="competitions").get(
            "competitions", []
        )

    def seasons(self) -> list[dict]:
        return self.get("seasons.json", cache_key="seasons").get("seasons", [])

    def sport_event_summary(self, event_id: str) -> dict:
        """One match's own summary feed. Worth checking against the daily feed:
        a per-event endpoint sometimes carries statistics the bulk feed omits."""
        safe = event_id.replace(":", "_")
        return self.get(f"sport_events/{event_id}/summary.json",
                        cache_key=f"event_{safe}")

    def rankings(self) -> list[dict]:
        """Current ATP/WTA rankings. One snapshot -- the feed carries no history,
        so applying these points to a season of past matches assumes a player's
        standing is roughly stable over the window."""
        return self.get("rankings.json", cache_key="rankings").get("rankings", [])


# ---------------------------------------------------------------------------
# Flattening: Sportradar competitor statistics -> Match Charting Project columns
# ---------------------------------------------------------------------------
#
#   MCP column      Sportradar source (c = this player, o = the opponent)
#   -------------   ---------------------------------------------------------
#   serve_pts       c.service_points_won + c.service_points_lost
#   aces            c.aces
#   dfs             c.double_faults
#   first_in        c.first_serve_successful
#   first_won       c.first_serve_points_won
#   second_in       c.second_serve_successful + c.double_faults
#   second_won      c.second_serve_points_won
#   return_pts      o.service_points_won + o.service_points_lost
#   return_pts_won  o.service_points_lost
#   bk_pts          o.total_breakpoints      (break points c faced)
#   bp_saved        o.total_breakpoints - o.breakpoints_won
#   winners         sum of c's winner categories + c.aces
#   unforced        sum of c's unforced-error categories + c.double_faults
#
# Break points are recorded from the returner's side, hence the o.* lookups.

NAN = float("nan")

# How the shot categories overlap, verified against a full day of live data:
#
#   forehand_* + backhand_* == groundstroke_* + volley_*
#
# The wing counters (forehand/backhand) label *which side* the shot came off
# and so include volleys; groundstroke_* is the rally-stroke count with volleys
# excluded. Summing wings and volleys together would count every volley twice.
# drop shot / lob / overhead / return are disjoint from both.
_WINNER_ROLLUP = "groundstroke_winners"
_WINNER_WINGS = ("forehand_winners", "backhand_winners")
_WINNER_VOLLEY = "volley_winners"
_WINNER_OTHERS = (
    "drop_shot_winners",
    "lob_winners",
    "overhead_stroke_winners",
    "return_winners",
)
_UE_ROLLUP = "groundstroke_unforced_errors"
_UE_WINGS = ("forehand_unforced_errors", "backhand_unforced_errors")
_UE_VOLLEY = "volley_unforced_errors"
_UE_OTHERS = (
    "drop_shot_unforced_errors",
    "lob_unforced_errors",
    "overhead_stroke_unforced_errors",
)


def _stats(competitor: dict) -> dict:
    """Statistics dict with whitespace stripped out of the key names."""
    return {
        str(k).replace(" ", ""): v
        for k, v in (competitor.get("statistics") or {}).items()
    }


def _num(stats: dict, key: str) -> float:
    """One statistic, or NaN when Sportradar did not collect it for this match."""
    value = stats.get(key)
    return NAN if value is None else float(value)


def _sum_present(stats: dict, keys) -> tuple[float, int]:
    total, present = 0.0, 0
    for key in keys:
        value = stats.get(key)
        if value is not None:
            total += float(value)
            present += 1
    return total, present


def _shot_total(stats: dict, rollup: str, wings, volley: str, others) -> float:
    """Total winners (or unforced errors) across every shot category, counting
    each shot exactly once.

    Prefers `rollup` + volleys; falls back to the wing counters, which already
    carry volleys inside them. Returns NaN when no shot category was collected
    at all -- these stats only exist at events with enhanced coverage, and NaN
    lets the tuning loop drop that one target instead of training on a fake 0.
    """
    base, n_base = _sum_present(stats, (rollup,))
    if n_base:
        base += _sum_present(stats, (volley,))[0]  # rollup excludes volleys
    else:
        base, n_base = _sum_present(stats, wings)  # wings already include them
    other, n_other = _sum_present(stats, others)
    if n_base == 0 and n_other == 0:
        return NAN
    total = base + other
    if total == 0:
        # Fields present but every rally category zero. Seen across all of
        # French Open qualifying: the keys are emitted, nothing was scored.
        # A real match does not go 148 points without a single winner, so this
        # is "not collected" wearing the costume of a real observation -- and
        # left as 0 it trains `shot` and `cons` toward a match nobody played.
        return NAN
    return total


def _norm_name(name: str) -> str:
    """Sportradar writes 'Sinner, Jannik'; the notebook expects 'Jannik Sinner'."""
    if "," in name:
        last, first = name.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return name.strip()


def _slug(text: str) -> str:
    """Underscore-only token, so '-' stays a field separator inside match_id."""
    return "".join(ch if ch.isalnum() else "_" for ch in str(text)).strip("_")


def _surface(sport_event: dict, context: dict) -> str | None:
    for holder in (context.get("competition") or {}, sport_event.get("venue") or {}):
        if holder.get("surface"):
            return holder["surface"]
    return None


def flatten_summaries(summaries: list[dict], singles_only: bool = True) -> pd.DataFrame:
    """Two rows per completed singles match -- one per player, MCP columns."""
    rows = []
    for summary in summaries:
        sport_event = summary.get("sport_event") or {}
        status = summary.get("sport_event_status") or {}
        if status.get("status") not in ("ended", "closed"):
            continue

        context = sport_event.get("sport_event_context") or {}
        competition = context.get("competition") or {}
        if singles_only and competition.get("type") not in (None, "singles"):
            continue

        entrants = sport_event.get("competitors") or []
        totals = ((summary.get("statistics") or {}).get("totals") or {}).get(
            "competitors"
        ) or []
        if len(entrants) != 2 or len(totals) != 2:
            continue  # doubles pairing, walkover with no stats, or a bye

        stats_by_id = {c.get("id"): _stats(c) for c in totals}
        if any(cid not in stats_by_id for cid in (e.get("id") for e in entrants)):
            continue

        names = [_norm_name(e.get("name", "")) for e in entrants]
        start_time = pd.to_datetime(sport_event.get("start_time"), utc=True, errors="coerce")
        if pd.isna(start_time):
            continue
        day = start_time.strftime("%Y%m%d")
        rnd = context.get("round") or {}
        match_id = "-".join(
            [
                day,
                _slug(competition.get("gender", "unknown")),
                _slug(competition.get("name", "unknown")),
                _slug(rnd.get("name") or rnd.get("number") or "unknown"),
                _slug(names[0]),
                _slug(names[1]),
            ]
        )

        for idx, entrant in enumerate(entrants):
            opponent = entrants[1 - idx]
            own = stats_by_id[entrant["id"]]
            opp = stats_by_id[opponent["id"]]

            service_won = _num(own, "service_points_won")
            service_lost = _num(own, "service_points_lost")
            opp_service_won = _num(opp, "service_points_won")
            opp_service_lost = _num(opp, "service_points_lost")
            opp_bp = _num(opp, "total_breakpoints")
            opp_bp_won = _num(opp, "breakpoints_won")

            rows.append(
                {
                    "match_id": match_id,
                    "player": names[idx],
                    "opponent": names[1 - idx],
                    "set": "Total",  # mirrors the MCP 'Total' row
                    # --- serve ---
                    "serve_pts": service_won + service_lost,
                    "aces": _num(own, "aces"),
                    "dfs": _num(own, "double_faults"),
                    "first_in": _num(own, "first_serve_successful"),
                    "first_won": _num(own, "first_serve_points_won"),
                    # MCP counts second-serve points *played*, double faults
                    # included, and the model's 0.48 second-serve baseline was
                    # calibrated on that. Sportradar counts second serves that
                    # landed, so add the double faults back in.
                    "second_in": _num(own, "second_serve_successful") + _num(own, "double_faults"),
                    "second_won": _num(own, "second_serve_points_won"),
                    # --- break points faced (recorded on the returner) ---
                    "bk_pts": opp_bp,
                    "bp_saved": opp_bp - opp_bp_won,
                    # --- return ---
                    "return_pts": opp_service_won + opp_service_lost,
                    "return_pts_won": opp_service_lost,
                    # --- rally ---
                    # Sportradar's shot categories cover rally shots only. The
                    # Match Charting Project -- which the model's 0.165 winner
                    # and 0.185 unforced baselines were fitted against -- also
                    # counts an ace as a winner and a double fault as an
                    # unforced error. Adding them back cut the mean absolute
                    # difference against MCP from 6.9 to 2.1 on winners.
                    # NaN propagates, so rows without shot coverage stay NaN.
                    "winners": _shot_total(
                        own, _WINNER_ROLLUP, _WINNER_WINGS, _WINNER_VOLLEY, _WINNER_OTHERS
                    ) + _num(own, "aces"),
                    "unforced": _shot_total(
                        own, _UE_ROLLUP, _UE_WINGS, _UE_VOLLEY, _UE_OTHERS
                    ) + _num(own, "double_faults"),
                    # --- context ---
                    # scouts occasionally lose a point or two; this is the
                    # residual of first_in + second_in + dfs - serve_pts
                    "serve_gap": (
                        _num(own, "first_serve_successful")
                        + _num(own, "second_serve_successful")
                        + _num(own, "double_faults")
                        - (service_won + service_lost)
                    ),  # 0 when the scout's serve counts close
                    "match_date": int(day),
                    "start_time": start_time,
                    "gender": competition.get("gender"),
                    "competition": competition.get("name"),
                    "level": competition.get("level"),
                    "surface": _surface(sport_event, context),
                    "round": rnd.get("name") or rnd.get("number"),
                    "player_id": entrant.get("id"),
                    "opponent_id": opponent.get("id"),
                    "won": status.get("winner_id") == entrant.get("id"),
                    "winning_reason": status.get("winning_reason"),
                }
            )

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _daterange(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def load_match_stats(
    start: date | str,
    end: date | str,
    gender: str | None = None,
    levels: tuple[str, ...] | None = None,
    client: Client | None = None,
    singles_only: bool = True,
    confirm_cost: bool = True,
    max_serve_gap: float = 3,
    tour_only: bool = True,
    include_challengers: bool = False,
    drop_inconsistent: bool = True,
) -> pd.DataFrame:
    """Every completed match between two dates, as MCP-shaped rows.

    One API call per uncached day, so the whole range is priced up front and
    refused if it would blow the remaining budget -- better than discovering
    that halfway through and leaving the quota spent on a partial pull.
    """
    start = pd.to_datetime(start).date()
    end = pd.to_datetime(end).date()
    client = client or Client()

    days = list(_daterange(start, end))
    uncached = [d for d in days if not client._cache_path(f"daily_{d.isoformat()}_0").exists()]
    if confirm_cost and len(uncached) > client.budget - client.requests_made:
        raise BudgetExceeded(
            f"{len(days)} days requested, {len(uncached)} not cached, but only "
            f"{client.budget - client.requests_made} requests left in this session's "
            f"budget. Narrow the range, or pass Client(budget=...) on purpose."
        )

    summaries = []
    for day in days:
        summaries.extend(client.daily_summaries(day))

    df = flatten_summaries(summaries, singles_only=singles_only)
    if df.empty:
        return df
    if gender:
        df = df[df["gender"] == gender]
    if levels:
        df = df[df["level"].isin(levels)]
    elif tour_only:
        # Only official ATP/WTA main-tour and slam competitions carry a `level`.
        # Everything else in the daily feed -- Challengers, ITF, and a flood of
        # UTR Pro Tennis Tour exhibitions -- leaves it null, and including them
        # buries the tour regulars under ~1,200 one-off players.
        keep = df["level"].notna()
        if include_challengers:
            # Challengers are the one unlevelled tier worth keeping: real ATP
            # ranking-point events, identifiable by name, and where much of the
            # field below the top 100 actually plays. They are ATP-only -- the
            # WTA equivalent already carries level `wta_125`.
            is_challenger = df["competition"].str.contains("Challenger", case=False, na=False)
            df = df.copy()
            df.loc[is_challenger, "level"] = "challenger"
            keep = keep | is_challenger
        df = df[keep]
    if max_serve_gap is not None:
        # A handful of rows have serve counts that do not close -- off by 10 or
        # 20 points, not one or two -- which wrecks every serve-side ratio.
        df = df[df["serve_gap"].abs() <= max_serve_gap]
    if drop_inconsistent:
        df = invalidate_inconsistent(df)
    return df.reset_index(drop=True)


def load_season_stats(
    season_ids,
    gender: str | None = None,
    client: Client | None = None,
    singles_only: bool = True,
) -> pd.DataFrame:
    """Same frame, sourced per tournament season -- ~1 call per event instead
    of one per day. Cheapest way to cover a fixed set of tournaments."""
    client = client or Client()
    summaries = []
    for season_id in season_ids:
        summaries.extend(client.season_summaries(season_id))
    df = flatten_summaries(summaries, singles_only=singles_only)
    if df.empty:
        return df
    if gender:
        df = df[df["gender"] == gender]
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

STAT_COLUMNS = (
    "serve_pts", "aces", "dfs", "first_in", "first_won", "second_in",
    "second_won", "bk_pts", "bp_saved", "return_pts", "return_pts_won",
    "winners", "unforced",
)


def logical_violations(df: pd.DataFrame) -> pd.Series:
    """Rows where a numerator exceeds its own denominator.

    These pass the `serve_gap` check because the serve totals still add up --
    what is wrong is the first/second classification. A scout logs every point
    as a first serve in, so second_serve_successful falls to 0 while
    second_serve_points_won stays in double figures, and
    second_won / second_in comes out at 9.0 instead of somewhere near 0.5.
    Rare (~0.1% of rows) but ruinous: the tuning loop reads that 9.0 as a real
    target and takes one enormous step on it.
    """
    return pd.concat([mask for _, mask in _violation_masks(df)], axis=1).any(axis=1)


def _violation_masks(df: pd.DataFrame):
    """(columns to invalidate, mask) for each impossible relationship."""
    return [
        (("second_won", "second_in"), df["second_won"] > df["second_in"]),
        (("first_won", "first_in"), df["first_won"] > df["first_in"]),
        # bp_saved is derived as opponent total_breakpoints - breakpoints_won,
        # so it goes negative when the feed reports more break points won than
        # faced -- systematic at Roland Garros.
        (("bp_saved", "bk_pts"), (df["bp_saved"] > df["bk_pts"]) | (df["bp_saved"] < 0)),
        (("return_pts_won", "return_pts"), df["return_pts_won"] > df["return_pts"]),
        (("first_in",), df["first_in"] > df["serve_pts"]),
    ]


def invalidate_inconsistent(df: pd.DataFrame) -> pd.DataFrame:
    """NaN out only the statistics that break a hard bound, keeping the rest.

    A row whose break-point counters are broken still has perfectly good serve
    and return numbers, and the tuning loop already drops individual targets by
    weighting them 0 -- so invalidating the pair beats discarding the match.
    """
    df = df.copy()
    for columns, mask in _violation_masks(df):
        if mask.any():
            df.loc[mask, list(columns)] = float("nan")
    return df


def coverage_report(df: pd.DataFrame) -> pd.DataFrame:
    """Share of rows carrying each stat -- shot-level fields are only collected
    at events with enhanced coverage, so `winners`/`unforced` run far thinner
    than the serve columns."""
    return pd.DataFrame(
        {
            "present": [df[c].notna().sum() for c in STAT_COLUMNS],
            "missing": [df[c].isna().sum() for c in STAT_COLUMNS],
            "pct_present": [round(100 * df[c].notna().mean(), 1) for c in STAT_COLUMNS],
        },
        index=list(STAT_COLUMNS),
    )


def check_groundstroke_identity(summaries: list[dict]) -> pd.DataFrame:
    """Verify the overlap rule `_shot_total` relies on: that
    forehand_* + backhand_* equals groundstroke_* + volley_*. If this stops
    holding, `_shot_total` is double- or under-counting winners and errors."""
    checks = []
    for summary in summaries:
        totals = ((summary.get("statistics") or {}).get("totals") or {}).get("competitors") or []
        for competitor in totals:
            stats = _stats(competitor)
            for rollup, wings, volley in (
                (_WINNER_ROLLUP, _WINNER_WINGS, _WINNER_VOLLEY),
                (_UE_ROLLUP, _UE_WINGS, _UE_VOLLEY),
            ):
                if stats.get(rollup) is None:
                    continue
                wing_sum, present = _sum_present(stats, wings)
                if present == 0:
                    continue
                expected = float(stats[rollup]) + _sum_present(stats, (volley,))[0]
                checks.append(
                    {"field": rollup, "rollup_plus_volley": expected,
                     "wings_sum": wing_sum, "equal": expected == wing_sum}
                )
    if not checks:
        return pd.DataFrame(columns=["field", "n", "pct_equal"])
    checked = pd.DataFrame(checks)
    return (
        checked.groupby("field")["equal"]
        .agg(n="size", pct_equal=lambda s: round(100 * s.mean(), 1))
        .reset_index()
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="spend exactly one request to verify the key works")
    args = parser.parse_args()

    if args.check:
        client = Client(budget=1)
        try:
            competitions = client.competitions()
            print(f"OK -- key accepted. {len(competitions)} competitions visible.")
            for competition in competitions[:5]:
                print(f"  {competition.get('id')}  {competition.get('name')}")
        except SportradarError as exc:
            raise SystemExit(f"FAILED\n{exc}")
