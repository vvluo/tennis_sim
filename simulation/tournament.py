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

MAX_DRAW = 256
MIN_QUALIFYING_DRAW = 16        # smaller than this, everyone is a direct entrant
MIN_SEEDS_KEEP = 4              # fewer seeded positions than this means none
DRAW_SIZE = 128                # the slam default; any size up to MAX_DRAW works
QUALIFIER_SHARE = 1 / 8        # 16 of 128, the slam's ratio, kept at every size


def bracket_for(draw: int) -> int:
    """The next power of two at or above `draw` -- the slots the draw sits in."""
    size = 1
    while size < draw:
        size *= 2
    return size


MIN_SEEDS = 4


def seeds_for(draw: int) -> int:
    """How many seeded positions the draw carries.

    A quarter of the bracket is seeded -- 8 in a 32, 16 in a 64, 32 in a 128 --
    checked against 116 real ATP/WTA events at 250 level and above. Two rules
    bend that:

    * Byes are a seeding privilege, so there can never be more byes than seeds.
      A draw below three quarters of its bracket needs more byes than a quarter
      of the bracket provides, and the count rises to the next power of two that
      covers them. Every real draw size already satisfies this and is untouched.
    * Below four seeds a draw is not meaningfully seeded and gets none, which
      applies only to draws of eight or fewer. Any bye there goes to the
      best-ranked player without calling anyone a seed.
    """
    bracket = bracket_for(draw)
    needed = max(bracket // 4, bracket - draw)
    if needed < MIN_SEEDS:
        return 0
    seeds = 1
    while seeds < needed:
        seeds *= 2
    return min(seeds, bracket // 2)


def round_names(bracket: int) -> list[str]:
    """R256 ... R16, then the three rounds everyone names instead."""
    names, size = [], bracket
    while size >= 2:
        names.append({2: 'F', 4: 'SF', 8: 'QF'}.get(size, f'R{size}'))
        size //= 2
    return names


def exit_labels(names: list[str]) -> dict[str, str]:
    """What a player's exit round is called when they lose in it."""
    return {n: (f'{i + 1}R' if n.startswith('R') else n) for i, n in enumerate(names)}


ROUND_NAMES = round_names(DRAW_SIZE)
EXIT_LABELS = exit_labels(ROUND_NAMES)


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
                draw_size: int = DRAW_SIZE,
                dropout: float = 0.10, qualifying_dropout: float = 0.60):
    """The 128 who actually turn up.

    Direct entry walks down the ranking list, each player declining with
    probability `dropout`, until 112 have accepted. Qualifiers come from the
    players that walk passed over, with a much heavier `qualifying_dropout`
    standing in for having to win three matches to get in.
    """
    # Below 16 a draw is too small to run a qualifying event worth modelling.
    qualifiers_wanted = 0 if draw_size < MIN_QUALIFYING_DRAW else round(draw_size * QUALIFIER_SHARE)
    direct_wanted = draw_size - qualifiers_wanted

    ranked = sorted(candidates, key=lambda c: c['rank'])

    accepted, index = [], 0
    for index, entry in enumerate(ranked):
        if len(accepted) == direct_wanted:
            break
        if rng.random() >= dropout:
            accepted.append(entry)

    # Qualifying draws only from players the direct-entry list never reached.
    # Someone who declined a main-draw place has withdrawn from the event; they
    # do not reappear by winning three qualifying matches.
    qualifiers = []
    for entry in ranked[index:]:
        if len(qualifiers) == qualifiers_wanted:
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
    for seed, entrant in enumerate(sorted(field, key=lambda e: e.rank)[:seeds_for(draw_size)], 1):
        entrant.seed = seed
    return field


# --------------------------------------------------------------------------
# draw
# --------------------------------------------------------------------------

def seeding_order(sections: int):
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


def seed_sections(rng: random.Random, sections: int):
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


def build_draw(field, rng: random.Random, draw_size: int = DRAW_SIZE):
    """Seat the field in its bracket. Empty seats are byes.

    N players sit in a bracket of the next power of two, so 2^b - c seats stay
    empty for N = 2^b + c. Byes go to the top seeds one each; a small draw can
    need more byes than it has seeds -- nine players in a sixteen bracket need
    seven -- and the remainder fall randomly on unseeded pairs.
    """
    if len(field) != draw_size:
        raise ValueError(f'need {draw_size} entrants, got {len(field)}')

    bracket = bracket_for(draw_size)
    seeds = seeds_for(draw_size)
    section_size = bracket // seeds if seeds else bracket
    byes = bracket - draw_size

    slots: list[Entrant | None] = [None] * bracket
    sections = seed_sections(rng, seeds) if seeds else {}
    seeded = {e.seed: e for e in field if e.seed}

    seat_of = {}
    for seed, section in sections.items():
        seat = section * section_size
        seat_of[seed] = seat
        slots[seat] = seeded.get(seed)

    empty: set[int] = set()
    placed = 0
    for seed in range(1, seeds + 1):
        if placed >= byes:
            break
        seat = seat_of.get(seed)
        if seat is None:
            continue
        empty.add(seat ^ 1)              # the other half of that first-round pair
        placed += 1

    # A small draw can need more byes than it has seeds -- nine players in a
    # sixteen bracket need seven -- and the surplus goes on down the ranking
    # rather than at random: a bye is a reward for standing, so it is handed out
    # best-ranked first, exactly as the seeded byes above are.
    rest = sorted((e for e in field if e.seed is None), key=lambda e: e.rank)
    surplus = max(0, byes - placed)
    bye_getters, others = rest[:surplus], rest[surplus:]
    rng.shuffle(others)

    if surplus:
        seed_seats = set(seat_of.values())
        pairs = [i for i in range(0, bracket, 2)
                 if i not in empty and i + 1 not in empty
                 and i not in seed_seats and i + 1 not in seed_seats]
        rng.shuffle(pairs)               # which pair is still drawn
        for entrant, pair in zip(bye_getters, pairs):
            seat = pair if rng.random() < 0.5 else pair + 1
            slots[seat] = entrant
            empty.add(seat ^ 1)

    spare = iter(others)
    for index in range(bracket):
        if slots[index] is not None or index in empty:
            continue
        slots[index] = next(spare, None)
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
                   final_set_tiebreak: int = 10, shrink: float = 1.0,
                   base: dict | None = None):
    """Play it out. Returns every round's matches in bracket order.

    `draw` may hold empty seats: those are byes, and the player opposite walks
    through without a match. The round names follow the bracket, so a 48 draw
    starts at R64 and a 28 draw at R32.
    """
    entrants = [e for e in draw if e is not None]
    mean_rating = sum(sum(e.ratings[k] for k in ('SRV', 'RET', 'SHOT', 'CONS')) / 4
                      for e in entrants) / len(entrants)
    shift = 5.0 - mean_rating
    for entrant in entrants:
        entrant.player = to_player(entrant, shift, shrink)

    names = round_names(len(draw))
    labels = exit_labels(names)
    rounds, alive = [], list(draw)
    for name in names:
        matches, winners = [], []
        for i in range(0, len(alive), 2):
            top, bottom = alive[i], alive[i + 1]
            if top is None or bottom is None:
                through = top or bottom
                if through is not None:
                    matches.append({'round': name, 'top': top, 'bottom': bottom,
                                    'winner': through, 'loser': None,
                                    'match': None, 'bye': True})
                    winners.append(through)
                continue
            played = Match(top.player, bottom.player, best_of=best_of,
                           final_set_tiebreak=final_set_tiebreak, base=base)
            won_by_top = played.winner_id == top.player.id
            winner, loser = (top, bottom) if won_by_top else (bottom, top)
            matches.append({'round': name, 'top': top, 'bottom': bottom,
                            'winner': winner, 'loser': loser,
                            'match': played, 'bye': False})
            winners.append(winner)
        rounds.append({'name': name, 'matches': matches})
        alive = winners

    champion = alive[0]
    playable = next((e for e in entrants if e.playable), None)
    result = None
    if playable:
        result = 'Win' if playable is champion else next(
            labels[m['round']] for r in rounds for m in r['matches']
            if m['loser'] is playable)
    return {'rounds': rounds, 'champion': champion,
            'playable': playable, 'playable_result': result}
