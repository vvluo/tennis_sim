from pathlib import Path

def get_player_name(player_id, player_names=None):
    """Resolve player ID to name using mapping dict or default."""
    if player_names and player_id in player_names:
        return player_names[player_id]
    return f"Player {player_id}"

def abbrev_name(full_name):
    """Abbreviate: first char of first name + all chars of last name (everything after first space)."""
    full_name = full_name.strip()
    if ' ' not in full_name:
        return full_name
    first, last = full_name.split(' ', 1)  # maxsplit=1 keeps the rest together
    return f"{first[:1]} {last}"


def tennis_score(server_points, receiver_points, server_id, receiver_id, player_names=None, tiebreaker=False, tiebreaker_win_points=7):
    # Full names here: abbreviating is a presentation choice, and the page makes
    # it from the width it actually has. Baking it into the record throws away
    # information the renderer needs.
    server_name = get_player_name(server_id, player_names)
    receiver_name = get_player_name(receiver_id, player_names)

    if tiebreaker:

        if server_points >= tiebreaker_win_points and server_points - receiver_points >= 2:
            return f'Game {server_name}'
        elif receiver_points >= tiebreaker_win_points and receiver_points - server_points >= 2:
            return f'Game {receiver_name}'
        else:
            return f'{server_name} {server_points} - {receiver_points} {receiver_name}'

    # --- normal game scoring, on the same abbreviated names ---
    if server_points >= 4 and server_points - receiver_points >= 2:
        return f'Game {server_name}'
    elif receiver_points >= 4 and receiver_points - server_points >= 2:
        return f'Game {receiver_name}'
    elif server_points < 3 or receiver_points < 3:
        score_map = {0: "0", 1: "15", 2: "30", 3: "40"}
        return f"{score_map[server_points]} - {score_map[receiver_points]}"
    elif server_points == receiver_points:
        return "40 - 40"
    elif server_points > receiver_points:
        return f'Ad {server_name}'
    else:
        return f'Ad {receiver_name}'

def format_point_record(point_record, player_names, server_id, receiver_id, cumulative_server_points, cumulative_receiver_points, tiebreaker=False):
    winner_id, shots = point_record[0], point_record[1]
    winner_name = get_player_name(winner_id, player_names)
    shot_text = "shot" if shots == 1 else "shots"
    
    current_score = tennis_score(cumulative_server_points, cumulative_receiver_points, server_id, receiver_id, player_names, tiebreaker=tiebreaker)
    
    return f"""
    <div class='point-row'>
        <span class='point-info'><span class='point-winner'>{winner_name}</span> ({shots} {shot_text})</span>
        <span class='point-score'>{current_score}</span>
    </div>
    """


def format_game_record(game_record, player_names, game_index, total_games_in_set, games_before_this):
    _, server_id, winner_id, num_points, point_records = game_record
    
    winner_name = get_player_name(winner_id, player_names)
    winner_name_abbrev = abbrev_name(winner_name)
    
    set_winner_id = games_before_this['set_winner_id']
    games_for_winner = games_before_this['set_winner_games']
    games_for_loser = games_before_this['set_loser_games']
    
    if winner_id == set_winner_id:
        games_for_winner += 1
    else:
        games_for_loser += 1
    
    cumulative_score = f"{games_for_winner} - {games_for_loser}"
    
    # derive receiver_id from the actual players in this match, not assuming 1 and 2
    receiver_id = games_before_this['other_player_id'] if server_id == games_before_this['set_winner_id'] else games_before_this['set_winner_id']

    points_html_parts = []
    server_points_won = 0
    receiver_points_won = 0
    
    is_tiebreak = total_games_in_set == 13 and game_index == 12

    for point_record in point_records:
        point_winner_id = point_record[0]
        if point_winner_id == server_id:
            server_points_won += 1
        else:
            receiver_points_won += 1
        
        points_html_parts.append(format_point_record(
            point_record,
            player_names,
            server_id,
            receiver_id,
            server_points_won,
            receiver_points_won,
            tiebreaker=is_tiebreak
        ))
    
    points_html = "".join(points_html_parts)
    
    if is_tiebreak:
        return f"""
    <div class='collapsible-container'>
        <div class='collapsible-header game-tiebreak' onclick='toggleCollapsible(this)'>
            <span class='toggle-icon'>▶</span>
            <span class='header-text'>Tiebreak - Winner: {winner_name} ({num_points} points)</span>
            <span class='game-score'>{cumulative_score}</span>
        </div>
        <div class='collapsible-content' style='display: none;'>
            {points_html}
        </div>
    </div>
    """
    else:
        server_name = get_player_name(server_id, player_names)
        server_name_abbrev = abbrev_name(server_name)
        is_hold = server_id == winner_id
        color_class = 'game-hold' if is_hold else 'game-break'
        hold_break_text = 'Hold' if is_hold else 'Break'
        
        return f"""
    <div class='collapsible-container'>
        <div class='collapsible-header game-header {color_class}' onclick='toggleCollapsible(this)'>
            <span class='toggle-icon'>▶</span>
            <span class='header-text'>Game - Server: {server_name_abbrev}, Winner: {winner_name_abbrev} ({num_points} points)</span>
            <span class='game-score'>{hold_break_text} {cumulative_score}</span>
        </div>
        <div class='collapsible-content' style='display: none;'>
            {points_html}
        </div>
    </div>
    """

def calculate_set_score(set_record):
    _, _, winner_id, num_games, game_records = set_record
    
    player1_games = sum(1 for gr in game_records if gr[2] == 1)
    player2_games = sum(1 for gr in game_records if gr[2] == 2)
    
    winner_games = sum(1 for gr in game_records if gr[2] == winner_id)
    loser_games  = sum(1 for gr in game_records if gr[2] != winner_id)

    if num_games <= 12:
        score_str = f"{winner_games} - {loser_games}"
    else:
        tiebreak_game = game_records[-1]
        _, _, tiebreak_winner_id, total_points, point_records = tiebreak_game
        loser_id = next(pid for pid in set(gr[2] for gr in game_records) if pid != tiebreak_winner_id)
        loser_points = sum(1 for pr in point_records if pr[0] == loser_id)
        score_str = f"7 - 6 ({loser_points})"
    
    return player1_games, player2_games, score_str

def format_set_record(set_record, player_names):
    _, _, winner_id, num_games, game_records = set_record
    
    winner_name = get_player_name(winner_id, player_names)
    p1_games, p2_games, score_str = calculate_set_score(set_record)

    # derive the other player id from the game records directly
    all_player_ids = set()
    for gr in game_records:
        all_player_ids.add(gr[1])  # server_id
        all_player_ids.add(gr[2])  # winner_id
    all_player_ids.discard(winner_id)
    other_player_id = all_player_ids.pop() if all_player_ids else None

    games_html = ""
    for game_index, gr in enumerate(game_records):
        games_before_this = {
            'set_winner_id': winner_id,
            'other_player_id': other_player_id,
            'set_winner_games': sum(1 for g in game_records[:game_index] if g[2] == winner_id),
            'set_loser_games':  sum(1 for g in game_records[:game_index] if g[2] != winner_id)
        }
        games_html += format_game_record(gr, player_names, game_index, num_games, games_before_this)
    
    html = f"""
    <div class='collapsible-container'>
        <div class='collapsible-header set-header' onclick='toggleCollapsible(this)'>
            <span class='toggle-icon'>▶</span>
            <span class='header-text'>Set - Winner: {winner_name}, {score_str}</span>
        </div>
        <div class='collapsible-content set-content' style='display: none;'>
            {games_html}
        </div>
    </div>
    """
    return html, score_str, winner_id

def generate_match_html(match_record, player1_name="Player 1", player2_name="Player 2", match_number=None):
    _, _, winner_id, num_sets, set_records = match_record

    # extract actual player IDs
    all_player_ids = set()
    for sr in set_records:
        _, _, _, _, game_records = sr
        for gr in game_records:
            all_player_ids.add(gr[1])
            all_player_ids.add(gr[2])
    all_player_ids = sorted(all_player_ids)
    id_a, id_b = all_player_ids[0], all_player_ids[1]

    player_names = {
        id_a: player1_name,
        id_b: player2_name,
    }

    winner_name = get_player_name(winner_id, player_names)
    loser_id = id_b if winner_id == id_a else id_a  # ← was: 2 if winner_id == 1 else 1
    loser_name = get_player_name(loser_id, player_names)
    
    # Build match sets HTML and collect scores
    set_htmls = []
    match_scores = []
    for sr in set_records:
        html, score_str, set_winner_id = format_set_record(sr, player_names)
        set_htmls.append(html)
        
        # If set winner is the match loser, flip the score
        if set_winner_id == loser_id:
            # Parse and flip the score
            if "(" in score_str:  # Tiebreak format like "7 - 6 (10)"
                parts = score_str.split(" - ")
                parts[0], parts[1] = parts[1].split("(")[0].strip(), parts[0]
                flipped = f"{parts[1]} - {parts[0]} ({score_str.split('(')[1]}"
                match_scores.append(flipped)
            else:
                parts = score_str.split(" - ")
                match_scores.append(f"{parts[1]} - {parts[0]}")
        else:
            match_scores.append(score_str)
    
    sets_html = "".join(set_htmls)
    match_score_str = ", ".join(match_scores)
    
    # Build match number display if provided
    match_number_html = ""
    if match_number is not None:
        match_number_html = f"<div class='match-number'>#{match_number}</div>"
    
    match_header_content = f"""
    <div class='match-header-content'>
        {match_number_html}
        <div>
            <h2>{winner_name} def. {loser_name}</h2>
            <div class='match-score'>{match_score_str}</div>
        </div>
    </div>
    """
    
    html = f"""
    <div class='match-container'>
        <div class='match-header'>
            {match_header_content}
        </div>
        <div class='match-content'>
            {sets_html}
        </div>
    </div>
    """
    return html

def clean_player_name(name):
    """Remove '_copy' suffix from player names."""
    if isinstance(name, str) and name.endswith('_copy'):
        return name[:-5]  # Remove '_copy' suffix
    return name

def generate_matches_html(matches):
    matches_htmls = []
    
    for match_num, match in enumerate(matches, 1):
        match_record = match.get_match_record()
        _, _, winner_id, num_sets, set_records = match_record

        # extract actual player IDs from the record
        all_player_ids = set()
        for sr in set_records:
            _, _, _, _, game_records = sr
            for gr in game_records:
                all_player_ids.add(gr[1])  # server_id
                all_player_ids.add(gr[2])  # winner_id
        all_player_ids = sorted(all_player_ids)
        id_a, id_b = all_player_ids[0], all_player_ids[1]

        # resolve names from the match object's actual players, keyed by their real ID
        player_name_by_id = {}
        for player in [match.server, match.receiver]:
            pid = player.id  # use the player's actual ID
            player_name_by_id[pid] = clean_player_name(player.name)

        player1_name = player_name_by_id.get(id_a, f"Player {id_a}")
        player2_name = player_name_by_id.get(id_b, f"Player {id_b}")

        match_html = generate_match_html(match_record, player1_name, player2_name, match_number=match_num)
        matches_htmls.append(match_html)
    
    matches_content = "".join(matches_htmls)
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Tennis Simulator</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f5f5f5;
            }}
            .page-title {{
                text-align: center;
                font-size: 36px;
                font-weight: bold;
                margin-bottom: 30px;
                color: #333;
            }}
            .matches-container {{
                display: flex;
                flex-direction: column;
                gap: 30px;
            }}
            .match-container {{
                background-color: white;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                overflow: hidden;
            }}
            .match-header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 25px;
            }}
            .match-header-content {{
                display: flex;
                align-items: center;
                gap: 20px;
            }}
            .match-number {{
                font-size: 24px;
                font-weight: bold;
                white-space: nowrap;
                min-width: 50px;
            }}
            .match-header h2 {{
                margin: 0;
                font-size: 24px;
            }}
            .match-score {{
                margin-top: 10px;
                font-size: 18px;
            }}
            .match-content {{
                padding: 20px;
            }}
            .collapsible-container {{
                margin-bottom: 15px;
                background-color: #f9f9f9;
                border-radius: 4px;
                border-left: 4px solid #667eea;
            }}
            .collapsible-header {{
                background-color: #e8e8ff;
                padding: 15px;
                cursor: pointer;
                display: flex;
                align-items: center;
                gap: 10px;
                font-weight: 600;
                color: #333;
                user-select: none;
                transition: background-color 0.2s;
            }}
            .collapsible-header:hover {{
                background-color: #d8d8ff;
            }}
            .collapsible-header.set-header {{
                background-color: #f0f0ff;
            }}
            .collapsible-header.set-header:hover {{
                background-color: #e0e0ff;
            }}
            .collapsible-header.game-header .game-score {{
                margin-left: auto;
            }}
            .collapsible-header.game-hold {{
                background-color: #e8f5e9;
            }}
            .collapsible-header.game-hold:hover {{
                background-color: #c8e6c9;
            }}
            .collapsible-header.game-break {{
                background-color: #ffebee;
            }}
            .collapsible-header.game-break:hover {{
                background-color: #ffcdd2;
            }}
            .collapsible-header.game-tiebreak {{
                background-color: #fffde7;
            }}
            .collapsible-header.game-tiebreak:hover {{
                background-color: #ffeb3b;
            }}
            .toggle-icon {{
                display: inline-block;
                transition: transform 0.2s;
                font-size: 12px;
                width: 20px;
            }}
            .collapsible-header.open .toggle-icon {{
                transform: rotate(90deg);
            }}
            .collapsible-content {{
                padding: 15px;
                padding-left: 30px;
                background-color: white;
            }}
            .point-row {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 10px 15px;
                margin-bottom: 8px;
                background-color: #f9f9f9;
                border-radius: 4px;
                border: 1px solid #e0e0e0;
            }}
            .point-winner {{
                font-weight: 600;
                color: #333;
            }}
            .point-shots {{
                color: #666;
                font-size: 14px;
            }}
        </style>
    </head>
    <body>
        <div class='page-title'>Tennis Simulator</div>
        <div class='matches-container'>
            {matches_content}
        </div>
        <script>
            function toggleCollapsible(header) {{
                header.classList.toggle('open');
                const content = header.nextElementSibling;
                if (content.style.display === 'none') {{
                    content.style.display = 'block';
                }} else {{
                    content.style.display = 'none';
                }}
            }}
        </script>
    </body>
    </html>
    """
    return html

# Flask endpoint setup (optional - only if Flask is installed)
try:
    from flask import Flask, jsonify, request
    
    app = Flask(__name__)
    
    @app.route('/match', methods=['POST'])
    def render_match():
        """
        Endpoint to render a match record as HTML.
        
        Expects JSON with:
        {
            "match_record": (match record tuple),
            "player1_name": "name" (optional),
            "player2_name": "name" (optional)
        }
        """
        try:
            data = request.get_json()
            match_record = tuple(data.get('match_record'))
            player1_name = data.get('player1_name', 'Player 1')
            player2_name = data.get('player2_name', 'Player 2')
            
            html = generate_match_html(match_record, player1_name, player2_name)
            return html, 200, {'Content-Type': 'text/html; charset=utf-8'}
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    
    @app.route('/health', methods=['GET'])
    def health():
        """Health check endpoint."""
        return jsonify({"status": "ok"}), 200
    
    _flask_available = True
except ImportError:
    _flask_available = False

if __name__ == '__main__' and _flask_available:
    app.run(debug=True, port=5000)


# ---------------------------------------------------------------------------
# Board output: data inlined as JSON and rendered in the browser, matching how
# ratings_board.html works. The older generate_matches_html pre-renders every
# point as static markup, which came to 799 KB for twenty matches.
# ---------------------------------------------------------------------------

def _players_in(match):
    """Real player ids -> display names, from the match object itself."""
    return {p.id: clean_player_name(p.name) for p in (match.player1, match.player2)}


def _game_payload(record, names, tiebreak_length=7):
    """One game or tiebreak: server, winner, and the running score per point.

    `tiebreak_length` matters: a deciding-set breaker runs to 10, and scoring it
    as though it ran to 7 declares "Game" the moment someone leads 7-5 and then
    keeps printing it while the players are still on court.
    """
    kind, server_id, winner_id, _, point_records = record
    other = [i for i in names if i != server_id]
    receiver_id = other[0] if other else server_id

    points, server_points, receiver_points = [], 0, 0
    for point in point_records:
        point_winner_id, shots, first_serve = point[0], point[1], (point[2] if len(point) > 2 else True)
        if point_winner_id == server_id:
            server_points += 1
        else:
            receiver_points += 1
        points.append({
            'w': names.get(point_winner_id, str(point_winner_id)),
            'n': shots,
            'f': first_serve,
            's': tennis_score(server_points, receiver_points, server_id, receiver_id,
                              names, tiebreaker=(kind == 'tiebreak'),
                              tiebreaker_win_points=tiebreak_length),
        })
    return {
        'kind': kind,
        'server': names.get(server_id, ''),
        'winner': names.get(winner_id, ''),
        'points': points,
    }


def match_payload(match, number):
    """One match as plain data: sets, games, points, and the final score."""
    _, _, winner_id, _, set_records = match.get_match_record()
    names = _players_in(match)
    winner = names.get(winner_id, '')
    loser = next((n for i, n in names.items() if i != winner_id), '')

    sets, score_parts = [], []
    final_set = len(set_records) - 1
    # Only a match that went the full distance has a deciding set, and only that
    # set's breaker runs to the long length. The winner took to_win sets, so the
    # distance is 2 * to_win - 1.
    to_win = sum(1 for s in set_records if s[2] == winner_id)
    deciding_set = final_set if len(set_records) == 2 * to_win - 1 else None
    long_tiebreak = getattr(match, 'final_set_tiebreak', 7)
    for set_index, set_record in enumerate(set_records):
        _, _, set_winner_id, _, game_records = set_record
        length = long_tiebreak if set_index == deciding_set else 7
        games = [_game_payload(g, names, length) for g in game_records]

        # Running games score after each game, always from the match winner's
        # side, so a scoreline reads the same way down the whole match.
        won = lost = 0
        for game in games:
            if game['kind'] == 'tiebreak':
                # The tiebreak is the 13th game and settles the set at 7-6. The
                # bracket after the 6 carries the points the set loser took in
                # the tiebreak, so 6(5)-7 reads as "lost the breaker 5-7".
                breaker_winner = sum(1 for pt in game['points'] if pt['w'] == game['winner'])
                breaker_loser = len(game['points']) - breaker_winner
                if game['winner'] == winner:
                    won, lost = 7, 6
                    game['score'] = f'7-6({breaker_loser})'
                else:
                    won, lost = 6, 7
                    game['score'] = f'6({breaker_loser})-7'
                continue
            elif game['winner'] == winner:
                won += 1
            else:
                lost += 1
            game['score'] = f'{won}-{lost}'
        # the set score is whatever the last game left, brackets included
        score_parts.append(games[-1]['score'] if games else f'{won}-{lost}')

        # The point that ends a set says so, and the one that ends the match
        # says that instead -- "Game John" alone loses the moment.
        if games and games[-1]['points']:
            closing = games[-1]
            label = 'Game Set Match' if set_index == final_set else 'Game Set'
            closing['points'][-1]['s'] = f"{label} {closing['winner']}"
        sets.append({
            'winner': names.get(set_winner_id, ''),
            'score': score_parts[-1],
            'games': games,
        })

    stats, stat_names = match_stats(match)
    return {
        'n': number,
        'stats': stats,
        'statNames': stat_names,
        'winner': winner,
        'loser': loser,
        'score': ', '.join(score_parts),
        'sets': sets,
        'points': sum(len(g['points']) for s in sets for g in s['games']),
    }


def match_stats(match):
    """Per-player match statistics, read back off the point records.

    Aces are not here: the simulator records an unreturned serve as a one-shot
    point and never distinguishes a clean ace from a serve the returner reached
    but could not put back, so counting them would be inventing a number.
    Double faults are exact -- they are the zero-shot points.
    """
    names = _players_in(match)
    ids = list(names)
    zero = {i: 0 for i in ids}
    stat = {key: dict(zero) for key in (
        'double_faults', 'first_serves', 'first_won', 'second_serves', 'second_won',
        'serve_points', 'serve_points_won', 'serve_games', 'serve_games_won',
        'return_points_won', 'points_won', 'games_won', 'tiebreaks_won',
        'break_points', 'break_points_won', 'unreturned', 'rally_shots', 'rallies')}

    point_streak = {i: 0 for i in ids}
    game_streak = {i: 0 for i in ids}
    best_points = dict(zero)
    best_games = dict(zero)

    for set_record in match.get_match_record()[4]:
        for game in set_record[4]:
            kind, server_id, game_winner_id, _, points = game
            receiver_id = next(i for i in ids if i != server_id)

            stat['games_won'][game_winner_id] += 1
            if kind == 'tiebreak':
                stat['tiebreaks_won'][game_winner_id] += 1
            else:
                stat['serve_games'][server_id] += 1
                if game_winner_id == server_id:
                    stat['serve_games_won'][server_id] += 1

            for winner in ids:
                game_streak[winner] = game_streak[winner] + 1 if winner == game_winner_id else 0
                best_games[winner] = max(best_games[winner], game_streak[winner])

            server_points = receiver_points = 0
            for point in points:
                point_winner, shots = point[0], point[1]
                first_serve = point[2] if len(point) > 2 else True

                # a break point is one the receiver could win the game with
                if kind != 'tiebreak':
                    needed = receiver_points + 1
                    if needed >= 4 and needed - server_points >= 2:
                        stat['break_points'][receiver_id] += 1
                        if point_winner == receiver_id:
                            stat['break_points_won'][receiver_id] += 1

                stat['serve_points'][server_id] += 1
                stat['points_won'][point_winner] += 1
                if point_winner == server_id:
                    stat['serve_points_won'][server_id] += 1
                else:
                    stat['return_points_won'][receiver_id] += 1

                if shots == 0:
                    stat['double_faults'][server_id] += 1
                elif shots == 1:
                    stat['unreturned'][server_id] += 1
                else:
                    stat['rally_shots'][server_id] += shots
                    stat['rallies'][server_id] += 1

                if first_serve:
                    stat['first_serves'][server_id] += 1
                    if point_winner == server_id:
                        stat['first_won'][server_id] += 1
                else:
                    stat['second_serves'][server_id] += 1
                    if point_winner == server_id:
                        stat['second_won'][server_id] += 1

                for winner in ids:
                    point_streak[winner] = point_streak[winner] + 1 if winner == point_winner else 0
                    best_points[winner] = max(best_points[winner], point_streak[winner])

                if point_winner == server_id:
                    server_points += 1
                else:
                    receiver_points += 1

    def pct(num, den, i):
        return f'{round(100 * num[i] / den[i])}%' if den[i] else '-'

    def ratio(num, den, i):
        return num[i] / den[i] if den[i] else None

    def count(key):
        return lambda i: stat[key][i]

    # (label, how it reads, what it compares on, is more of it better)
    # Only double faults reward the lower number. Avg rally length has no better
    # side, so it falls back to the higher figure like everything else.
    rows = [
        ('Double faults',        lambda i: str(stat['double_faults'][i]),
                                 count('double_faults'), False),
        ('First serve %',        lambda i: pct(stat['first_serves'], stat['serve_points'], i),
                                 lambda i: ratio(stat['first_serves'], stat['serve_points'], i), True),
        ('Win % on 1st serve',   lambda i: pct(stat['first_won'], stat['first_serves'], i),
                                 lambda i: ratio(stat['first_won'], stat['first_serves'], i), True),
        ('Win % on 2nd serve',   lambda i: pct(stat['second_won'], stat['second_serves'], i),
                                 lambda i: ratio(stat['second_won'], stat['second_serves'], i), True),
        ('Break points',         lambda i: f"{stat['break_points_won'][i]}/{stat['break_points'][i]}",
                                 count('break_points_won'), True),
        ('Unreturned serves',    lambda i: str(stat['unreturned'][i]),
                                 count('unreturned'), True),
        ('Avg rally length',     lambda i: (f"{stat['rally_shots'][i] / stat['rallies'][i]:.1f}"
                                            if stat['rallies'][i] else '-'),
                                 lambda i: ratio(stat['rally_shots'], stat['rallies'], i), True),
        ('Service points won',   lambda i: str(stat['serve_points_won'][i]),
                                 count('serve_points_won'), True),
        ('Service games won',    lambda i: f"{stat['serve_games_won'][i]}/{stat['serve_games'][i]}",
                                 count('serve_games_won'), True),
        ('Receiving points won', lambda i: str(stat['return_points_won'][i]),
                                 count('return_points_won'), True),
        ('Points won',           lambda i: str(stat['points_won'][i]),
                                 count('points_won'), True),
        ('Games won',            lambda i: str(stat['games_won'][i]),
                                 count('games_won'), True),
        ('Max points in a row',  lambda i: str(best_points[i]),
                                 lambda i: best_points[i], True),
        ('Max games in a row',   lambda i: str(best_games[i]),
                                 lambda i: best_games[i], True),
        ('Tiebreaks won',        lambda i: str(stat['tiebreaks_won'][i]),
                                 count('tiebreaks_won'), True),
    ]

    out = []
    for label, display, value, higher_is_better in rows:
        left, right = value(ids[0]), value(ids[1])
        better = None
        if left is not None and right is not None and left != right:
            leads = left > right
            better = 'a' if leads == higher_is_better else 'b'
        out.append({'label': label, 'a': display(ids[0]), 'b': display(ids[1]),
                    'better': better})
    return out, [names[ids[0]], names[ids[1]]]


DEFAULT_TEMPLATE = Path(__file__).with_name('match_board_template.html')


def generate_matches_board(matches, path='match_output.html', template=None):
    """Write the interactive board, inlining the match data into the template.

    The template ships beside this module, so it is found however the caller
    was launched; `path` stays relative to the working directory, since that is
    where you want the output.
    """
    import json

    payload = [match_payload(m, i) for i, m in enumerate(matches, 1)]
    page = Path(template or DEFAULT_TEMPLATE).read_text().replace(
        '/*__DATA__*/', json.dumps(payload, separators=(',', ':')))
    Path(path).write_text(page)
    return payload
