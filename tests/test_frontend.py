import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simulation import Player, Tour
from simulation.frontend import generate_matches_board

if __name__ == '__main__':
    t = Tour()
    # volatility is opt-in: without it a player has no match-to-match form swing.
    # Higher means steadier, matching every other rating.
    roster = [
        Player('Matt',               5.0,  5.0,  5.0,  5.0, volatility=5.0),
        Player('John',              10.0,  5.0,  5.0,  5.0, volatility=2.0),
        Player('Diego',              5.0,  5.0, 10.0,  5.0, volatility=8.0),
        Player('Nikolay Davydenko',  5.0,  5.0,  5.0, 10.0, volatility=5.0),
        Player('David Ferrer',       5.0, 10.0,  5.0,  5.0, volatility=10.0),
    ]
    for player in roster:
        t.add_player(player)

    matt, opponents = roster[0], roster[1:]
    matches = [t.play_match(matt, opponent, best_of=3)
               for opponent in opponents
               for _ in range(5)]

    payload = generate_matches_board(matches)
    points = sum(m['points'] for m in payload)
    print(f'\u2713 {len(matches)} matches, {points:,} points -> match_output.html')
