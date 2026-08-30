from .tour import Tour
from .match import Match
from .player import Player
import numpy as np
import matplotlib.pyplot as plt
import time
from multiprocessing import Pool, cpu_count
from functools import partial

def main() -> None:
    """Execution"""
    t = Tour()
    easy_bot = Player('Bob')
    normal_bot = Player('Matt', 5.0, 5.0, 5.0, 5.0)
    serve_bot = Player('John', 10.0, 5.0, 5.0, 5.0)
    return_bot = Player('Diego', 5.0, 5.0, 10.0, 5.0)
    shot_bot = Player('Nikolay Davydenko', 5.0, 5.0, 5.0, 10.0)
    consistency_bot = Player('David Ferrer', 5.0, 10.0, 5.0, 5.0)
    t.add_player(easy_bot)
    t.add_player(normal_bot)
    t.add_player(serve_bot)
    t.add_player(return_bot)
    t.add_player(shot_bot)
    t.add_player(consistency_bot)

    win_1, win_2, matches = sim_batch(t, normal_bot, consistency_bot, threads=100, best_of=3)
    print(f"Normal bot wins: {win_1}, Other bot wins: {win_2}")
    print(f'Match number 10: {matches[9].get_match_record()}')
    
def set_length_tester():
    t = Tour()
    easy_bot = Player('Bob')
    normal_bot = Player('Matt', 5.0, 5.0, 5.0, 5.0)
    serve_bot = Player('John', 10.0, 5.0, 5.0, 5.0)
    return_bot = Player('Diego', 5.0, 5.0, 10.0, 5.0)
    t.add_player(easy_bot)
    t.add_player(normal_bot)
    t.add_player(serve_bot)
    t.add_player(return_bot)

    set_lengths = []
    m = t.play_match(serve_bot, easy_bot, best_of=1)
    for _ in range(2000):
        winner, info = m.sim_set()
        set_lengths.append(info[3])
    
    plt.hist(set_lengths, bins=np.arange(0, max(set_lengths)+1)+0.5, density=True)
    plt.xlabel('Set Length (Games)')
    plt.ylabel('Density')
    plt.title('Distribution of Set Lengths')
    plt.show()

def point_length_tester():
    t = Tour()
    easy_bot = Player('Bob')
    normal_bot = Player('Matt', 5.0, 5.0, 5.0, 5.0)
    serve_bot = Player('John', 10.0, 5.0, 5.0, 5.0)
    t.add_player(easy_bot)
    t.add_player(normal_bot)

    point_lengths = []
    m = t.play_match(serve_bot, easy_bot, best_of=1)
    for _ in range(2000):
        m.server = serve_bot
        m.receiver = easy_bot
        _, info = m.simulate_point(first_serve=True)
        point_lengths.append(info[1])
    
    plt.hist(point_lengths, bins=np.arange(0, max(point_lengths)+1)-0.5, density=True)
    plt.xlabel('Point Length')
    plt.ylabel('Density')
    plt.title('Distribution of Point Lengths')
    plt.show()


def _simulate_single_match(args):
    """Worker entry point: one match, no Tour, no registry."""
    a, b, best_of = args
    return Match(a, b, best_of=best_of)


def sim_batch(t: Tour, a: Player, b: Player, threads=100, best_of=3,
              parallel=False, workers=None, chunksize=None):
    """Simulate `threads` copies of a match between a and b.

    Sequential by default. A match takes about 0.33 ms, so handing 100 of them
    to a process pool spent ~9 s on startup, pickling the Player objects out and
    the full Match objects -- every point record included -- back again, against
    42 ms of actual work. Running them in-process is ~200x faster and, because
    Match._id_counter is per-process, also stops match ids colliding between
    workers.

    parallel=True keeps a real pool for runs big enough to pay for it: a
    cpu_count()-sized pool with chunked tasks, worth reaching for somewhere
    north of ~100k matches.

    Args:
        t: Tour object (unused -- these matches are not registered in it)
        a: Player A
        b: Player B
        threads: number of matches to simulate
        best_of: sets format for each match
        parallel: use a process pool instead of running in-process
        workers: pool size, defaults to cpu_count()
        chunksize: matches per task, defaults to spreading ~4 chunks per worker

    Returns:
        Tuple of (wins_a, wins_b, matches_list)
    """
    if parallel:
        workers = workers or cpu_count()
        chunksize = chunksize or max(1, threads // (workers * 4))
        tasks = [(a, b.create_copy(), best_of) for _ in range(threads)]
        with Pool(processes=workers) as pool:
            matches = pool.map(_simulate_single_match, tasks, chunksize=chunksize)
    else:
        matches = [Match(a, b.create_copy(), best_of=best_of) for _ in range(threads)]

    wins_a = sum(1 for m in matches if m.winner_id == a.id)
    wins_b = sum(1 for m in matches if m.winner_id == b.id)

    return wins_a, wins_b, matches


if __name__ == "__main__":
    main()