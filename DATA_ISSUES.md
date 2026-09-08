# Sportradar Tennis v3 — open data questions

Observations from a year of daily summaries pulled on a **trial** key
(`/tennis/trial/v3/en/...`), window **2025-08-25 → 2026-08-25**: 42,295
player-match rows across 21,398 matches, ATP and WTA, tour level plus ATP
Challengers.

Each item below is a question of the same shape: **is this an entitlement limit
on our access level, or is the data not collected?** The answer changes what we
build, so we would rather know than guess.

---

## 1. Rally and shot statistics appear only at Grand Slam main draws

`winner_rate`, `unforced_error_rate` and every shot category are present on
**1,920 of 18,891 tour-level rows (10.2%)**, and their distribution is
completely deterministic rather than patchy:

| match type | coverage | rows |
| --- | --- | --- |
| Grand Slam main draw | **100%**, every round, all four slams, both tours | 1,921 |
| Grand Slam qualifying — Roland Garros only | 100% | 443 |
| Grand Slam qualifying — AO, Wimbledon, US Open | **0%** | 1,003 |
| Everything else (ATP 1000/500/250, WTA 1000/500/250/125, Challengers, Finals) | **0%** | 15,525 |

**172 of 180 competitions return no shot data at all.** Field counts confirm the
cliff: events with `enhanced_stats: true` return 37 statistics fields, all others
return 17, and no event in 56,338 observed returns more than 37.

**Mechanism, confirmed.** This is a per-match *coverage* property, not a tier or
an endpoint. Every event carries
`sport_event.coverage.sport_event_properties.{enhanced_stats,
detailed_serve_outcomes, play_by_play}`. Across ~57,000 matches,
`play_by_play` and `detailed_serve_outcomes` are true almost everywhere
(51,164 and 51,156), while **`enhanced_stats` is true on 1,941 — and only ever
at the four Grand Slams**, across singles, doubles and mixed. The flag predicts
the data exactly: shot totals are present in 79% of flagged matches and **0% of
unflagged ones**. We now record the flag per row, so the shot columns are
explicitly conditional rather than mysteriously absent. Enhanced coverage adds
21 per-stroke fields (`forehand_winners`, `backhand_unforced_errors`,
`volley_winners`, …) on top of the base 16; there is no aggregate `winners`
field, so shot totals must be summed from the stroke rollups.

A second, smaller oddity in the same area: **Roland Garros qualifying emits the
shot keys with 0 in all of them** — 443 rows where 148-point matches record zero
winners and zero unforced errors. We treat these as absent rather than as
observations, but a real zero and an unrecorded zero are indistinguishable in
the payload.

### What this rules out downstream

Not a separate issue — an implication of the above, and the one that actually
blocked work. **Surface effects on rally quality cannot be measured at all.**
Because shot data exists only at the slams, any surface comparison reduces to
*Roland Garros vs Wimbledon vs AO + US Open*: one tournament per surface, with
court speed confounded by ball, altitude, format and scheduling. **Indoor hard
has zero rows**, since no slam is played indoors.

Serve-side surface effects are fine — those statistics are on every match, so
clay, grass and indoor each draw on 35, 16 and 12 events respectively. It is
specifically winners and unforced errors that collapse to a single tournament
per surface.

Related, and likely the same question: five fields documented in the statistics
schema are **never returned on any event** —
`return_unforced_errors`, `service_unforced_errors`, `volley_errors`,
`overhead_errors`, `overhead_winners`. Meanwhile `overhead_stroke_errors` and
`overhead_stroke_winners` *are* returned under names the schema does not list,
and `return_errors` is returned but is 0 in all 3,632 blocks that contain it.

**Question:** is enhanced shot coverage restricted to slams on the trial tier,
or is it only ever collected at slam main draws? And are the five absent fields
gated, deprecated, or renamed?

---

## 2. WTA coverage falls away below roughly rank 250

Matching our data against the ATP and WTA ranking feeds (top 500 each, week
35/2026) by competitor id:

| rank band | ATP covered | WTA covered |
| --- | --- | --- |
| 1–250 | 100% | 100% |
| 251–300 | 100% | 98% |
| 301–400 | **100%** | **83%** |
| 401–500 | **100%** | **71%** |
| **overall** | **500/500 (100%)** | **453/500 (90.6%)** |

47 ranked WTA players have **no match in the feed for an entire year** —
Dencheva (#299), Shaikh (#306), Pavlova (#337), Vujovic (#350), Encheva (#353),
Cayetano (#368) and others.

**Correction (checked after Sportradar pointed us at the categories).** An
earlier version of this note claimed no ITF events exist in the feed. That was
wrong, and wrong for an avoidable reason: we searched competition *names* within
the ~180 competitions that returned rows, instead of the category taxonomy in
the full catalogue. The categories are there:

| category | id | competitions in catalogue |
| --- | --- | --- |
| ITF Men | `sr:category:785` | 2,198 |
| ITF Women | `sr:category:213` | 2,032 |
| Challenger | `sr:category:72` | 1,057 |
| WTA 125K | `sr:category:871` | 256 |

The real limit is narrower, and it is about statistics rather than coverage:

- **ITF Women events reach the daily feed, but carry no statistics.** 44 of the
  2,032 catalogued events appeared in our year, 242 matches in total, and
  **0 of them carry a statistics block**. Same for ITF Men: 465 matches, 0 with
  statistics.
- The ATP's second tier **is** carried with statistics — 16,316 Challenger
  matches, 95% with a statistics block — which is exactly why ATP ranks 250–500
  come out fully covered. `sr:category:72` is men-only in our window.
- WTA 125K carries 3,535 matches at 95%, and lifts ranked-WTA reach from 403 to
  458 players on its own.
- **UTR Women** is the one large uncounted women's dataset — 10,260 matches,
  86% with statistics — but it is a different population: of 1,546 players,
  only **34 are ranked WTA** and just 12 would become newly rateable. Including
  it would add ~1,500 unranked players to gain 12.

Counting every category, **467 of 500 ranked WTA players appear in at least one
match with a statistics block (93%)**; 33 have none anywhere in the year. So the
gap is not the category filter — it is that these players compete where
statistics are not collected.

**Question:** ITF Women events are in the feed but return no statistics block
on our tier. Is that an entitlement boundary — would a production key populate
statistics for ITF events — or are statistics not scouted at ITF level at all?
If the latter, the 33 missing players are permanently unrateable and we should
stop trying.

---

## 3. No match statistics available for earlier years

Daily summaries return **results** for historical dates, but never
**statistics**:

| date sampled | summaries | completed | with `statistics` | `enhanced_stats: true` |
| --- | --- | --- | --- | --- |
| 2021-09-01 | 126 | 123 | **0** | 0 |
| 2023-09-01 | 161 | — | **0** | 0 |
| 2024-09-01 | 579 | — | **0** | **20** |
| 2025-08-20 onward | ~150/day | — | present throughout | yes |

Schedules, scores, winners and `sport_event_status` are all intact back to at
least 2021. The `statistics` block is simply absent from every event on those
dates.

The 2024 row is the informative one: **20 events on 2024-09-01 carry
`enhanced_stats: true` in their coverage flags yet return no statistics block**.
That reads like a retention or entitlement boundary rather than data that was
never collected.

This matters because every rating we build is derived from the statistics block
— serve points, first-serve splits, break points, shot categories. Without it a
historical pull yields match outcomes only, which supports Elo-style rating from
results but none of the per-attribute work.

**Question:** is there a statistics retention window on the trial tier, and does
a production entitlement extend it? If so, how far back?

---

## 4. Backfill should not loop Daily Summaries

Noted for when a production entitlement opens the history: our loader walks the
calendar day by day, which cost **430 cached day-pages for one year** (375 days,
54 of them needing a second page at 200 matches per page). Sportradar's guidance
is to use **Season Summaries** (`seasons/{id}/summaries.json`) or Competitor
Summaries for a one-time backfill instead — far fewer calls for the same
matches, since we only care about ATP, WTA, WTA 125K and Challenger seasons
rather than every UTR and juniors match that shares the calendar.

`Client.season_summaries()` already exists in `sportradar_data.py` and has never
been called — there are zero `season_*` files in the cache. Worth measuring
before any historical pull, because on a trial key the day-by-day path would
exhaust the 1,000-call monthly quota on roughly two years of history.

## How these were checked

All figures are reproducible from `sportradar_data.py` against a local cache of
the daily summaries feed; the historical-year samples cost four live calls
total. Coverage percentages match on `competitor.id` rather than name.

The category, coverage and ITF figures in the corrected sections above were
recomputed from the existing cache — 430 day-pages plus the competitions
catalogue — and cost **no live calls**.
