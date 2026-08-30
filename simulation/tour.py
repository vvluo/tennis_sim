from .player import Player
from .match import Match
from collections import defaultdict

class Tour:
    def __init__(self):
        self.player_book: dict[int, Player] = dict()
        self.matches = defaultdict(list) # maps id to ids of matches played by that player
        self.match_dir: dict[int, Match] = dict()

    def add_player(self, player: Player):
        self.player_book[player.id] = player

    def play_match(self, p1: Player, p2: Player, best_of=3):
        if p1.id not in self.player_book:
            self.add_player(p1)
        if p2.id not in self.player_book:
            self.add_player(p2)
        match = Match(p1, p2, best_of=best_of)
        self.matches[p1.id].append(match.match_id)
        self.matches[p2.id].append(match.match_id)
        self.match_dir[match.match_id] = match
        return match
