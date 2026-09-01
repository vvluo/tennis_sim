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

The cause looks structural rather than incidental:

- **No ITF events exist in the feed for either tour.** Zero competitions contain
  "ITF" in the name, on either side.
- The ATP's second tier **is** carried — 240 Challenger events, 23,404 rows —
  which is exactly why ATP ranks 250–500 come out fully covered.
- The WTA's nearest equivalent in the feed is **WTA 125, only 65 events, 4,569
  rows** — one tier above where these players actually compete.
- Tournaments seen against live WTA rankings return **0 rows**: *Leiria*,
  *Tianjin 5*, *Saint Palais Sur Mer*. Checked as substrings across all 283
  women's competitions in the unfiltered feed.

**Question:** are ITF-level women's events (W15–W100) available on a different
access level or a separate feed, or are they outside Sportradar's tennis
coverage entirely?

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

## How these were checked

All figures are reproducible from `sportradar_data.py` against a local cache of
the daily summaries feed; the historical-year samples cost four live calls
total. Coverage percentages match on `competitor.id` rather than name.
