"""Replay the rating fit and log every update that moves one player's parameter.

Answers, for each update: what the target was, what the model predicted from the
parameter it held at that moment, what parameter value would have hit the target
exactly, and where the optimizer actually moved it.

    python trace_param.py "Carlos Alcaraz" srv
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from train_player_params import RatingModel

# Same weights the notebook's tuning cells use.
USER_WEIGHTS = {
    "ace_rate": 0.5,
    "df_rate": 1,
    "first_serve_in_rate": 1,
    "first_serve_pts_win_rate": 0.5,
    "second_serve_pts_win_rate": 1,
    "break_pts_save_rate": 0.5,
    "return_pts_win_rate": 1,
    "winner_rate": 1,
    "unforced_error_rate": 1,
}


def _rate(numerator, denominator):
    if not denominator or pd.isna(denominator) or pd.isna(numerator):
        return None
    return numerator / denominator


def row_targets(row):
    """The nine raw ratios for one player-match row, as the notebook builds them."""
    total_pts = row["serve_pts"] + row["return_pts"]
    raw = {
        "ace_rate": _rate(row["aces"], row["serve_pts"]),
        "df_rate": _rate(row["dfs"], row["serve_pts"]),
        "first_serve_in_rate": _rate(row["first_in"], row["serve_pts"]),
        "first_serve_pts_win_rate": _rate(row["first_won"], row["first_in"]),
        "second_serve_pts_win_rate": _rate(row["second_won"], row["second_in"]),
        "break_pts_save_rate": _rate(row["bp_saved"], row["bk_pts"]),
        "return_pts_win_rate": _rate(row["return_pts_won"], row["return_pts"]),
        "winner_rate": _rate(row["winners"], total_pts),
        "unforced_error_rate": _rate(row["unforced"], total_pts),
    }
    weights = {k: (0.0 if v is None else USER_WEIGHTS[k]) for k, v in raw.items()}
    targets = {k: (0.0 if v is None else v) for k, v in raw.items()}
    return targets, weights


def implied_value(model, key, i, j, target, player, attr, lo=-200.0, hi=200.0):
    """The parameter value that would have made this predictor hit the target
    exactly, holding every other parameter at its current value.

    Bisection rather than algebra: break_pts_save_rate is quadratic in srv and
    return_pts_win_rate is its complement, so one inversion covers all nine.
    Returns NaN when the target is unreachable at any parameter value.
    """
    original = model.params.data[player][attr].item()

    def f(value):
        model.params.data[player][attr] = value
        with torch.no_grad():
            return getattr(model, key)(i, j).item() - target

    try:
        f_lo, f_hi = f(lo), f(hi)
        if np.isnan(f_lo) or np.isnan(f_hi) or f_lo * f_hi > 0:
            return float("nan")
        for _ in range(200):
            mid = (lo + hi) / 2
            if f(lo) * f(mid) <= 0:
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2
    finally:
        model.params.data[player][attr] = original


def trace(df, player_name, attribute="srv", lr=5e-2, betas=(0.0, 0.999)):
    """Replay the whole frame in order, logging updates that touch one parameter.

    Every row is replayed, not just the traced player's, so the optimizer state
    and every other player's parameters evolve exactly as in the notebook.
    """
    attr = RatingModel.attribute_to_index[attribute]

    name_to_index = {}
    for _, row in df.iterrows():
        for name in (row["player"], row["opponent"]):
            if name not in name_to_index:
                name_to_index[name] = len(name_to_index)
    if player_name not in name_to_index:
        raise KeyError(f"{player_name!r} not in this frame")
    target_player = name_to_index[player_name]

    model = RatingModel(len(name_to_index))
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, betas=betas)
    mse = torch.nn.MSELoss()

    detail, summary = [], []
    for step, (_, row) in enumerate(df.iterrows(), start=1):
        i = name_to_index[row["player"]]
        j = name_to_index[row["opponent"]]
        targets, weights = row_targets(row)
        involved = target_player in (i, j)

        if involved:
            before = model.params[target_player][attr].item()
            per_predictor = []
            for key in RatingModel.PREDICTORS:
                w = weights[key]
                if w == 0:
                    continue
                pred = getattr(model, key)(i, j)
                term = w * mse(pred, torch.as_tensor(targets[key], dtype=pred.dtype))
                g = torch.autograd.grad(term, model.params, retain_graph=False,
                                        allow_unused=True)[0]
                contrib = 0.0 if g is None else g[target_player][attr].item()
                if contrib == 0.0:
                    continue  # this predictor does not read the traced parameter
                per_predictor.append({
                    "step": step,
                    "match_date": row["match_date"],
                    "competition": row["competition"],
                    "round": row["round"],
                    "role": "server" if i == target_player else "returner",
                    "opponent": row["opponent"] if i == target_player else row["player"],
                    "predictor": key,
                    "weight": w,
                    "target": targets[key],
                    "predicted": pred.item(),
                    "error": pred.item() - targets[key],
                    f"{attribute}_at_time": before,
                    f"implied_{attribute}": implied_value(
                        model, key, i, j, targets[key], target_player, attr),
                    "grad_contribution": contrib,
                })

        model.update(i, j, targets, optimizer, weights)

        if involved:
            after = model.params[target_player][attr].item()
            total_grad = model._grad_log[-1]
            gi = total_grad["grad_i"][attr].item() if i == target_player else None
            gj = total_grad["grad_j"][attr].item() if j == target_player else None
            detail.extend(per_predictor)
            summary.append({
                "step": step,
                "match_date": row["match_date"],
                "competition": row["competition"],
                "round": row["round"],
                "role": "server" if i == target_player else "returner",
                "opponent": row["opponent"] if i == target_player else row["player"],
                "n_predictors": len(per_predictor),
                f"{attribute}_before": before,
                "total_grad": gi if gi is not None else gj,
                f"{attribute}_after": after,
                "delta": after - before,
            })

    return pd.DataFrame(detail), pd.DataFrame(summary)


if __name__ == "__main__":
    import sys

    player = sys.argv[1] if len(sys.argv) > 1 else "Carlos Alcaraz"
    attribute = sys.argv[2] if len(sys.argv) > 2 else "srv"

    frame = pd.read_csv("sportradar_data/matches_2025-08-21_2026-08-21.csv")
    gender = "men" if player in set(frame[frame.gender == "men"]["player"]) else "women"
    frame = frame[frame.gender == gender].reset_index(drop=True)

    detail, summary = trace(frame, player, attribute)
    slug = player.lower().replace(" ", "_")
    detail.to_csv(f"sportradar_data/trace_{slug}_{attribute}_detail.csv", index=False)
    summary.to_csv(f"sportradar_data/trace_{slug}_{attribute}_summary.csv", index=False)
    print(f"{len(summary)} updates, {len(detail)} predictor contributions")
    print(f"wrote sportradar_data/trace_{slug}_{attribute}_[detail|summary].csv")
