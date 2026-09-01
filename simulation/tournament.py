"""Grand slam: field selection, the draw, and running it as single elimination.

    field  = build_field(candidates, rng, playable='Carlos Alcaraz')
    draw   = build_draw(field, rng)
    result = run_tournament(draw, rng, best_of=5)

`candidates` is the ranked pool: dicts with name, rank, and the four ratings on
the published 0-10 scale.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field as dc_field

from .match import Match
from .player import Player

DRAW_SIZE = 128
SEEDS = 32
DIRECT_ENTRANTS = 112          # 104 by rank + 8 wildcards in reality; we do not
QUALIFIERS = 16                # model the wildcard process, so they are ranked
SECTION_SIZE = DRAW_SIZE // SEEDS

ROUND_NAMES = ['R128', 'R64', 'R32', 'R16', 'QF', 'SF', 'F']
# what a player's exit round is called when they lose in it
EXIT_LABELS = {'R128': '1R', 'R64': '2R', 'R32': '3R', 'R16': '4R',
               'QF': 'QF', 'SF': 'SF', 'F': 'F'}


@dataclass
class Entrant:
    name: str
    rank: int | None
    ratings: dict                 # SRV / RET / SHOT / CONS, 0-10 published scale
    qualifier: bool = False
    playable: bool = False
    seed: int | None = None
    player: Player | None = None


# --------------------------------------------------------------------------
# field
# --------------------------------------------------------------------------

def build_field(candidates, rng: random.Random, playable: str | None = None,
                dropout: float = 0.10, qualifying_dropout: float = 0.60):
    """The 128 who actually turn up.

    Direct entry walks down the ranking list, each player declining with
    probability `dropout`, until 112 have accepted. Qualifiers come from the
    players that walk passed over, with a much heavier `qualifying_dropout`
    standing in for having to win three matches to get in.
    """
    ranked = sorted(candidates, key=lambda c: c['rank'])

    accepted, index = [], 0
    for index, entry in enumerate(ranked):
        if len(accepted) == DIRECT_ENTRANTS:
            break
        if rng.random() >= dropout:
            accepted.append(entry)

    # Qualifying draws only from players the direct-entry list never reached.
    # Someone who declined a main-draw place has withdrawn from the event; they
    # do not reappear by winning three qualifying matches.
    qualifiers = []
    for entry in ranked[index:]:
        if len(qualifiers) == QUALIFIERS:
            break
        if rng.random() >= qualifying_dropout:
            qualifiers.append(entry)

    field = ([Entrant(e['name'], e['rank'], e['ratings']) for e in accepted]
             + [Entrant(e['name'], e['rank'], e['ratings'], qualifier=True)
                for e in qualifiers])

    if playable:
        for entrant in field:
            if entrant.name == playable:
                entrant.playable = True
                break
        else:                                   # not in the field -- put them in
            custom = next((c for c in candidates if c['name'] == playable), None)
            if custom is None:
                raise KeyError(f'{playable!r} is not among the candidates')
            # Ranked below the last direct entrant means they did not earn a
            # main-draw place, so they enter through qualifying like anyone else
            # that far down the list.
            via_qualifying = bool(accepted) and custom['rank'] > accepted[-1]['rank']
            field[-1] = Entrant(custom['name'], custom['rank'], custom['ratings'],
                                qualifier=via_qualifying, playable=True)

    # seeds are the 32 best-ranked players who actually entered
    for seed, entrant in enumerate(sorted(field, key=lambda e: e.rank)[:SEEDS], 1):
        entrant.seed = seed
    return field


# --------------------------------------------------------------------------
# draw
# --------------------------------------------------------------------------

def seeding_order(sections: int = SEEDS):
    """Standard bracket order: which section each seed belongs in.

    Built by repeated mirroring, so seed 1 and seed 2 land at opposite ends,
    3 and 4 split the remaining quarters, and so on down.
    """
    order = [0]
    while len(order) < sections:
        size = len(order) * 2
        order = [x for pair in ((position, size - 1 - position) for position in order)
                 for x in pair]
    return order


def seed_sections(rng: random.Random, sections: int = SEEDS):
    """Seed number -> section, with the tiers shuffled inside themselves.

    The mirroring above fixes which *set* of sections a tier occupies; which
    seed of the tier gets which section is drawn, exactly as seeds 3-4 are drawn
    for the two open quarters and 5-8 for the four open eighths.
    """
    order = seeding_order(sections)

    # tiers are seeds 1, 2, 3-4, 5-8, 9-16, 17-32: each twice the last
    tiers, lo = [(0, 1), (1, 2)], 2
    while lo < sections:
        tiers.append((lo, min(lo * 2, sections)))
        lo *= 2

    assignment = {}
    for lo, hi in tiers:
        drawn = order[lo:hi]
        rng.shuffle(drawn)
        for offset, section in enumerate(drawn):
            assignment[lo + offset + 1] = section
    return assignment


def build_draw(field, rng: random.Random):
    """128 slots. Seeds take the head of their section, the rest fall in."""
    if len(field) != DRAW_SIZE:
        raise ValueError(f'need {DRAW_SIZE} entrants, got {len(field)}')

    slots: list[Entrant | None] = [None] * DRAW_SIZE
    sections = seed_sections(rng)
    seeded = {e.seed: e for e in field if e.seed}

    for seed, section in sections.items():
        slots[section * SECTION_SIZE] = seeded[seed]

    rest = [e for e in field if e.seed is None]
    rng.shuffle(rest)
    empty = [i for i, slot in enumerate(slots) if slot is None]
    for index, entrant in zip(empty, rest):
        slots[index] = entrant
    return slots


# --------------------------------------------------------------------------
# playing it
# --------------------------------------------------------------------------

# How much of the observed rating spread is skill rather than measurement noise.
# A rating is an estimate, and estimates overshoot: a player measured three points
# above average is usually somewhat less than three points above average in truth.
# Shrinking by the reliability of the estimate is the standard correction.
#
# Fitted against a year of real results, comparing the higher-rated player's win
# rate to the simulator's across bins of published OVR gap: ATP mean absolute
# error falls 0.047 -> 0.020 at 0.8, while the WTA already fits at 1.0 and is
# left alone. The gap between them is data volume -- the median ATP player has
# 5 tour matches in the window against the WTA's 18.
SHRINK = {'ATP': 0.8, 'WTA': 1.0}


def to_player(entrant: Entrant, shift: float, shrink: float = 1.0) -> Player:
    """Published ratings -> a simulator Player.

    The published ratings are min-max scaled, so their mean is not 5 -- but every
    constant in player.py is calibrated so that 5.0 produces tour-average rates.
    `shift` re-centres the field without touching the spread between players;
    `shrink` then pulls that spread in toward the middle. Both are order
    preserving, and neither touches the published ratings themselves.

    Volatility is deliberately NOT shrunk: it measures dispersion, not skill, so
    the reliability of a skill estimate has no bearing on it. It also reuses CONS
    for now. CONS is ~74% dispersion already, but the clean split is CONS_ERR /
    CONS_VOL, which the ratings export does not carry.
    """
    ratings = entrant.ratings

    def attribute(value):
        return 5.0 + shrink * (value + shift - 5.0)

    return Player(entrant.name,
                  attribute(ratings['SRV']), attribute(ratings['CONS']),
                  attribute(ratings['RET']), attribute(ratings['SHOT']),
                  volatility=ratings['CONS'] + shift)


def run_tournament(draw, rng: random.Random, best_of: int = 5,
                   final_set_tiebreak: int = 10, shrink: float = 1.0):
    """Play it out. Returns every round's matches in bracket order."""
    mean_rating = sum(sum(e.ratings[k] for k in ('SRV', 'RET', 'SHOT', 'CONS')) / 4
                      for e in draw) / len(draw)
    shift = 5.0 - mean_rating
    for entrant in draw:
        entrant.player = to_player(entrant, shift, shrink)

    rounds, alive = [], list(draw)
    for name in ROUND_NAMES:
        matches, winners = [], []
        for i in range(0, len(alive), 2):
            top, bottom = alive[i], alive[i + 1]
            played = Match(top.player, bottom.player,
                           best_of=best_of, final_set_tiebreak=final_set_tiebreak)
            won_by_top = played.winner_id == top.player.id
            winner, loser = (top, bottom) if won_by_top else (bottom, top)
            matches.append({'round': name, 'top': top, 'bottom': bottom,
                            'winner': winner, 'loser': loser, 'match': played})
            winners.append(winner)
        rounds.append({'name': name, 'matches': matches})
        alive = winners

    champion = alive[0]
    playable = next((e for e in draw if e.playable), None)
    result = None
    if playable:
        result = 'Win' if playable is champion else next(
            EXIT_LABELS[m['round']] for r in rounds for m in r['matches']
            if m['loser'] is playable)
    return {'rounds': rounds, 'champion': champion,
            'playable': playable, 'playable_result': result}
