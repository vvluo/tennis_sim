import random
from typing import NamedTuple


class Player:
    _id_counter_player = 1
    def __init__(self, name, serve_quality=0.0, consistency=0.0, return_quality=0.0, shot_quality=0.0, volatility=None, competitive=True, copied_id = None):
        self.name = f'{name}_copy' if not competitive else name
        self.competitive = competitive
        if competitive:
            self.id = self.__class__._id_counter_player
            self.__class__._id_counter_player += 1
        else:
            assert copied_id is not None, "Non-competitive player must have an associated competitive player ID"
            self.id = copied_id
        self.serve_quality = serve_quality
        self.consistency = consistency
        self.return_quality = return_quality
        self.shot_quality = shot_quality
        # How much this player's level swings from match to match. Higher means
        # steadier, matching every other rating. None disables form variation
        # entirely, so a player built without it behaves exactly as before.
        self.volatility = volatility

    def __eq__(self, other):
        if isinstance(other, Player):
            return self.id == other.id
        return False
    
    def __hash__(self):
        return hash(self.id)
    
    def is_competitive(self):
        return self.competitive
    
    def create_copy(self):
        return Player(self.name, self.serve_quality, self.consistency, self.return_quality, self.shot_quality, self.volatility, competitive=False, copied_id=self.id)

BASE_FIRST_SERVE_PERCENTAGE = 0.55
FIRST_SERVE_GRADIENT = 0.017
BASE_DOUBLE_FAULT_RATE = 0.06
DOUBLE_FAULT_GRADIENT = -0.003
FIRST_SERVE_BOOST = 0.14
SECOND_SERVE_BOOST = 0.0
RETURN_GRADIENT = 0.02
BASE_SHOT_ACCURACY = 0.78
BASE_INCONSISTENCY = 0.14
INCONSISTENCY_GRADIENT = -0.012
RALLY_ADVANTAGE_GRADIENT = 0.01

# Per-match form. A player does not arrive at the same level every week, and
# CONS_VOL measures exactly how much they move. Each of the four attributes gets
# its OWN offset, drawn independently once per player per match -- the serve can
# desert someone on a day their returning is fine. A single shared draw would
# make every good day a good day at everything, which overstates how far a
# player's whole level moves at once.
#
# Calibration: the noise-corrected match-to-match spread of first-serve-in rate
# is about 0.042 on the ATP, and FIRST_SERVE_GRADIENT is 0.017 per rating point,
# so an average player swings roughly 0.042 / 0.017 = 2.5 points. That is what
# volatility 5.0 produces here.
BASE_FORM_SD = 4.0
FORM_SD_GRADIENT = -0.3


class Form(NamedTuple):
    """One match's level offsets, in rating points, one per attribute."""
    serve: float = 0.0
    consistency: float = 0.0
    shot: float = 0.0
    ret: float = 0.0


NO_FORM = Form()


def draw_form(player: Player, rng=random) -> Form:
    """This player's four level offsets for one match, drawn independently.

    consistency gets a single offset even though it feeds two probabilities
    (double faults and unforced errors), because both come off the same
    attribute -- they are one thing measured in two places, not two things.
    """
    if player.volatility is None:
        return NO_FORM
    sd = max(BASE_FORM_SD + FORM_SD_GRADIENT * player.volatility, 0.0)
    if not sd:
        return NO_FORM
    return Form(rng.gauss(0.0, sd), rng.gauss(0.0, sd),
                rng.gauss(0.0, sd), rng.gauss(0.0, sd))


def _as_probability(value: float) -> float:
    """Keep a form-shifted rate inside [0, 1]; an extreme draw can push past it."""
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


class Matchup:
    def __init__(self, player: Player, opponent: Player, match_id: int,
                 player_form: Form = NO_FORM, opponent_form: Form = NO_FORM):
        self.player = player
        self.opponent = opponent
        self.match_id = match_id
        self.player_form = player_form
        self.opponent_form = opponent_form

        # Effective attributes for this match: the rating plus today's form.
        # Every probability below is built from these, so the numbers
        # simulate_point reads already carry the match's form.
        serve = player.serve_quality + player_form.serve
        consistency = player.consistency + player_form.consistency
        shot = player.shot_quality + player_form.shot
        opponent_return = opponent.return_quality + opponent_form.ret

        self.first_serve_percentage = _as_probability(BASE_FIRST_SERVE_PERCENTAGE + FIRST_SERVE_GRADIENT * serve)
        self.double_fault_rate = _as_probability(BASE_DOUBLE_FAULT_RATE + DOUBLE_FAULT_GRADIENT * consistency)
        self.inconsistency = _as_probability(BASE_INCONSISTENCY + INCONSISTENCY_GRADIENT * consistency)
        self.probability_of_serve_return = _as_probability(BASE_SHOT_ACCURACY + (opponent_return * 0.5 - serve) * RETURN_GRADIENT)
        self.first_serve_boost = FIRST_SERVE_BOOST
        self.second_serve_boost = SECOND_SERVE_BOOST
        self.prob_returnable = _as_probability(BASE_SHOT_ACCURACY + (opponent_return * 0.5 - shot) * RALLY_ADVANTAGE_GRADIENT)