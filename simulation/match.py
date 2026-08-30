# Stats source:
# https://www.research.unipd.it/retrieve/363f798b-13b5-4bd1-8a07-c61d455e901d/rally_publiished.pdf

from .player import Player, Matchup, draw_form
import random
class Match:
    _id_counter = 1

    def __init__(self, p1: Player, p2: Player, best_of=3):
        assert best_of % 2 == 1, "Best of must be an odd number"
        assert p1.id != p2.id, "Players must be different"
        self.player1 = p1
        self.player2 = p2
        # Four independent offsets per player per match. Both matchups see both
        # players' forms, since probability_of_serve_return pairs one player's
        # serve against the other's return and each side is having its own day.
        p1_form = draw_form(p1)
        p2_form = draw_form(p2)
        self.p1_matchup = Matchup(p1, p2, self.__class__._id_counter, p1_form, p2_form)
        self.p2_matchup = Matchup(p2, p1, self.__class__._id_counter, p2_form, p1_form)
        self.match_id = self.__class__._id_counter
        self.__class__._id_counter += 1
        self.match_record = None # collection of game records, grouped by sets
        coin_toss = random.random() < 0.5
        self.player1_id = p1.id
        self.server = self.player1 if coin_toss else self.player2
        self.receiver = self.player2 if coin_toss else self.player1
        self.sim_match(to_win = (best_of + 1) // 2)
        self.winner_id = self.match_record[2]

    @property
    def server(self):
        return self._server

    @server.setter
    def server(self, player):
        # Cached here so the point loop can test an int flag instead of running
        # Player.__eq__ -- that comparison fired ~115k times per 200 matches.
        self._server = player
        self._server_is_p1 = player.id == self.player1_id

    def __str__(self):
        winner_str = self.player1.name if self.match_record[2] == self.player1.id else self.player2.name
        return f"Match between {self.player1.name} and {self.player2.name}. Winner: {winner_str}"
    
    def get_match_record(self):
        return self.match_record

    def draw_rng(self):
        """Kept for callers outside this class. The hot loops below bind
        random.random directly -- the old 1000-deep prefill-and-pop buffer cost
        more in allocation and list churn than the C call it was wrapping."""
        return random.random()

    def decide_game(self, pts_1, pts_2, to_win=4):
        if pts_1 < to_win and pts_2 < to_win:
            return None
        elif pts_1 >= to_win and pts_1 - pts_2 >= 2:
            return self.player1
        elif pts_2 >= to_win and pts_2 - pts_1 >= 2:
            return self.player2
        else:
            return None

    def decide_set(self, games_1, games_2):
        if games_1 < 6 and games_2 < 6:
            return None
        elif games_1 >= 6 and games_1 - games_2 >= 2:
            return self.player1
        elif games_2 >= 6 and games_2 - games_1 >= 2:
            return self.player2
        elif games_1 == 7:
            return self.player1
        elif games_2 == 7:
            return self.player2
        elif games_1 == 6 and games_2 == 6:
            return 'tiebreak'
        else:
            return None

    def decide_match(self, p1_sets, p2_sets, to_win=2):
        if p1_sets >= to_win:
            return self.player1
        elif p2_sets >= to_win:
            return self.player2
        else:
            return None
    
    def sim_match(self, to_win=2):
        p1_sets = 0
        p2_sets = 0
        match_record = [] # collection of set records

        while not self.decide_match(p1_sets, p2_sets, to_win=to_win):
            set_winner, set_record = self.sim_set()
            match_record.append(set_record) # record the set details
            if set_winner is self.player1:
                p1_sets += 1
            else:
                p2_sets += 1
        winner = self.decide_match(p1_sets, p2_sets, to_win=to_win)
        self.match_record = ('match', None, winner.id, p1_sets + p2_sets, tuple(match_record))
        return winner


    def sim_set(self):
        games_1 = 0
        games_2 = 0
        set_record = [] # collection of game records

        while not self.decide_set(games_1, games_2) or self.decide_set(games_1, games_2) == 'tiebreak':
            if self.decide_set(games_1, games_2) == 'tiebreak':
                start_server, start_receiver = self.server, self.receiver
                tiebreak_winner, tiebreak_record = self.sim_tiebreak(start_server)
                set_record.append(tiebreak_record)
                self.server, self.receiver = start_receiver, start_server # switch servers for the next set after tiebreak
                return tiebreak_winner, ('set', None, tiebreak_winner.id, 13, tuple(set_record))
            game_winner, game_record = self.sim_game()
            if game_winner is self.player1:
                games_1 += 1
            else:
                games_2 += 1
            set_record.append(game_record) # record the score after each game
            self.server, self.receiver = self.receiver, self.server # switch servers for the next game
        winner = self.decide_set(games_1, games_2)
        return winner, ('set', None, winner.id, games_1 + games_2, tuple(set_record))

    def sim_tiebreak(self, first_server: Player, length=7):
        points_1 = 0
        points_2 = 0
        tiebreak_record = [] # collection of point records

        while not self.decide_game(points_1, points_2, to_win=length):
            point_winner, point_record = self.simulate_point()
            if point_winner is self.player1:
                points_1 += 1
            else:
                points_2 += 1
            tiebreak_record.append(point_record) # record the score after each point
            
            # Switch servers after the first point and then every two points
            if (points_1 + points_2) % 2 == 1:
                self.server, self.receiver = self.receiver, self.server
        
        winner = self.decide_game(points_1, points_2, to_win=length)
        return winner, ('tiebreak', first_server.id, winner.id, points_1 + points_2, tuple(tiebreak_record))

    def sim_game(self):
        # Calculate first serve percentage
        server_is_p1 = self._server_is_p1
        first_serve_percentage = self.p1_matchup.first_serve_percentage if server_is_p1 else self.p2_matchup.first_serve_percentage
        
        # Calculate double fault rate
        double_fault_rate = self.p1_matchup.double_fault_rate if server_is_p1 else self.p2_matchup.double_fault_rate
        pts_1 = 0
        pts_2 = 0
        game_record = [] # collection of point records

        rand = random.random
        while not self.decide_game(pts_1, pts_2):
            # Simulate point
            serve_rng = rand()
            server_is_p1 = self._server_is_p1

            if serve_rng < double_fault_rate:
                if server_is_p1:
                    pts_2 += 1
                else:
                    pts_1 += 1
                game_record.append((self.receiver.id, 0, False))
            elif serve_rng > 1 - first_serve_percentage:
                # First serve is in, calculate point outcome
                point_outcome, point_record = self.simulate_point(first_serve=True)
                if point_outcome is self.player1:
                    pts_1 += 1
                else:
                    pts_2 += 1
                game_record.append(point_record)
            else:
                # Second serve is in, calculate second serve outcome
                point_outcome, point_record = self.simulate_point(first_serve=False)
                if point_outcome is self.player1:
                    pts_1 += 1
                else:
                    pts_2 += 1
                game_record.append(point_record)
        winner = self.decide_game(pts_1, pts_2)
        return winner, ('game', self.server.id, winner.id, pts_1 + pts_2, tuple(game_record))

    def simulate_point(self, first_serve=True):
        rand = random.random
        server_is_p1 = self._server_is_p1
        server_matchup = self.p1_matchup if server_is_p1 else self.p2_matchup
        receiver_matchup = self.p2_matchup if server_is_p1 else self.p1_matchup
        
        inconsistency_server = server_matchup.inconsistency
        inconsistency_receiver = receiver_matchup.inconsistency
        probability_of_serve_return = server_matchup.probability_of_serve_return
        
        if first_serve:
            probability_of_serve_return -= server_matchup.first_serve_boost
        else:
            probability_of_serve_return -= server_matchup.second_serve_boost
        
        return_rng = rand()
        if return_rng > probability_of_serve_return or (rand() < inconsistency_receiver):
            return self.server, (self.server.id, 1, first_serve)  # unreturned serve

        shot_maker = self.receiver
        opposition = self.server
        shots = 2
        shot_maker_is_p1 = not server_is_p1
        
        while True:
            # Calculate shot accuracy and inconsistency
            shot_matchup = self.p1_matchup if shot_maker_is_p1 else self.p2_matchup
            prob_returnable = shot_matchup.prob_returnable
            response_rng = rand()
            shot_inconsistency = inconsistency_server if not shot_maker_is_p1 else inconsistency_receiver
            
            if response_rng > prob_returnable or (rand() < shot_inconsistency):
                if shot_maker is self.server:
                    return self.server, (self.server.id, shots, first_serve)  # Server wins the point
                else:
                    return self.receiver, (self.receiver.id, shots, first_serve)  # Receiver wins the point
            shots += 1
            shot_maker, opposition = opposition, shot_maker  # Switch roles for the next shot
            shot_maker_is_p1 = not shot_maker_is_p1