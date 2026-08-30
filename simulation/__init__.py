"""Point-by-point tennis match simulation.

    from simulation import Player, Tour
    from simulation.frontend import generate_matches_board

Run the demo with `python -m simulation.main`.
"""

from .player import Player, Matchup, Form, draw_form
from .match import Match
from .tour import Tour

__all__ = ['Player', 'Matchup', 'Form', 'draw_form', 'Match', 'Tour']
