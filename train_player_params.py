import torch
import torch.nn as nn

class RatingModel(nn.Module):
    attribute_to_index = {
        "srv": 0,
        "ret": 1,
        "shot": 2,
        "cons": 3,
    }

    def __init__(self, n_players):
        super().__init__()
        self.num_players = n_players

        self.params = nn.Parameter(torch.full((n_players, 4), 5.0))

        # log of the per-step gradients for the two players touched by update()
        self._grad_log = []

    # --- prediction functions ---------------------------------------------
    # Each returns one predicted rate for the matchup (server i, returner j),
    # named to match its target key. Abbreviations follow the spec:
    #   s = srv (idx 0), r = ret (idx 1), q = shot (idx 2), c = cons (idx 3)
    # player 1 = self.params[i], player 2 = self.params[j].

    def first_serve_in_rate(self, i, j):
        s1 = self.params[i][0]
        # F = 0.55 + 0.017 s1
        return 0.55 + 0.017 * s1

    def df_rate(self, i, j):
        c1 = self.params[i][3]
        # D = 0.06 - 0.003 c1
        return 0.06 - 0.003 * c1

    def first_serve_pts_win_rate(self, i, j):
        p1, p2 = self.params[i], self.params[j]
        s1, r1, q1, c1 = p1[0], p1[1], p1[2], p1[3]
        s2, r2, q2, c2 = p2[0], p2[1], p2[2], p2[3]

        return 0.68 + 0.01 * s1 - 0.01 * r2 + 0.02 * q1 - 0.02 * q2

        # I1 = 0.14 - 0.012 * c1
        # I2 = 0.14 - 0.012 * c2
        # R1 = 0.70 + 0.02 * r2 - 0.02 * s1
        # P1 = 0.78 + 0.02 * r2 - 0.02 * q1
        # P2 = 0.78 + 0.02 * r1 - 0.02 * q2
        # A = P1 * (1 - I1)
        # B = P2 * (1 - I2)

        # W1 = 1 - R1(1 - I2) + R1(1 - I2)(1 - B) / (1 - AB)
        # return 1 - R1 * (1 - I2) + R1 * (1 - I2) * (1 - B) / (1 - A * B)

    def second_serve_pts_win_rate(self, i, j):
        p1, p2 = self.params[i], self.params[j]
        s1, r1, q1, c1 = p1[0], p1[1], p1[2], p1[3]
        s2, r2, q2, c2 = p2[0], p2[1], p2[2], p2[3]

        return 0.48 + 0.01 * s1 - 0.01 * r2 + 0.02 * q1 - 0.02 * q2

        # I1 = 0.14 - 0.012 * c1
        # I2 = 0.14 - 0.012 * c2
        # R2 = 1 # 0.95 + 0.02 * r2 - 0.02 * s1
        # P1 = 0.78 + 0.02 * r2 - 0.02 * q1
        # P2 = 0.78 + 0.02 * r1 - 0.02 * q2
        # A = P1 * (1 - I1)
        # B = P2 * (1 - I2)

        # # W2 = 1 - R2(1 - I2) + R2(1 - I2)(1 - B) / (1 - AB)
        # return 1 - R2 * (1 - I2) + R2 * (1 - I2) * (1 - B) / (1 - A * B)

    def break_pts_save_rate(self, i, j):
        F = self.first_serve_in_rate(i, j)
        D = self.df_rate(i, j)
        W1 = self.first_serve_pts_win_rate(i, j)
        W2 = self.second_serve_pts_win_rate(i, j)
        # W = F * W1 + (1 - D - F) * W2
        return F * W1 + (1 - D - F) * W2

    def ace_rate(self, i, j):
        s1 = self.params[i][0]
        # ACE = 0.02 + 0.005 s1
        return 0.045 + 0.005 * s1

    def return_pts_win_rate(self, i, j):
        # player i returning against player j's serve: complement of the
        # (overall) serve pts win rate, with i and j swapped so j is serving.
        return 0.97 - self.break_pts_save_rate(j, i)

    def winner_rate(self, i, j):
        q1 = self.params[i][2]
        # WNR = 0.15 + 0.01 q1
        return 0.115 + 0.01 * q1

    def unforced_error_rate(self, i, j):
        c1 = self.params[i][3]
        # UE = 0.35 - 0.01 c1
        return 0.235 - 0.01 * c1

    # --- aggregate loss ----------------------------------------------------
    # Order of the prediction functions / weights:
    PREDICTORS = (
        "first_serve_pts_win_rate",
        "second_serve_pts_win_rate",
        "break_pts_save_rate",
        "first_serve_in_rate",
        "df_rate",
        "ace_rate",
        "return_pts_win_rate",
        "winner_rate",
        "unforced_error_rate",
    )

    def loss(self, i, j, targets, weights=None):
        """Weighted sum of per-target MSEs.

        loss = w1*mse(pred1, target1) + ... + wn*mse(predn, targetn)

        targets: dict keyed by (a subset of) the PREDICTORS names; predictors
        absent from targets are skipped, so callers can supply fewer targets
        than the full PREDICTORS set.
        weights: optional dict of the same keys (defaults to 1.0 each).
        """
        mse = nn.MSELoss()
        total = torch.tensor(0.0)
        for key in self.PREDICTORS:
            if key not in targets:
                continue
            pred = getattr(self, key)(i, j)
            w = 1.0 if weights is None else weights.get(key, 1.0)
            target = torch.as_tensor(targets[key], dtype=pred.dtype)
            total = total + w * mse(pred, target)
        l2_regularization = 0 # 1e-6 * ((self.params[i] - 5.0).pow(2).sum() + (self.params[j] - 5.0).pow(2).sum())
        total = total + l2_regularization
        return total

    def update(self, i, j, targets, optimizer, weights=None, steps=1):
        """Run `steps` Adam updates for the matchup (server i, returner j)
        toward `targets`, then return the two updated 4-parameter vectors.

        `optimizer` is passed in so its state (e.g. Adam moments) persists
        across repeated calls. Returns detached clones of params[i], params[j].
        """
        for _ in range(steps):
            optimizer.zero_grad()
            loss = self.loss(i, j, targets, weights)
            loss.backward()
            # record the gradients for players i and j before they are reset
            self._grad_log.append({
                'i': i,
                'j': j,
                'grad_i': self.params.grad[i].detach().clone(),
                'grad_j': self.params.grad[j].detach().clone(),
            })
            optimizer.step()
        return self.params[i].detach().clone(), self.params[j].detach().clone()

    def get_gradient_log(self):
        """Return the recorded per-step gradients.

        A list (in update order) of dicts with keys 'i', 'j', 'grad_i',
        'grad_j', where grad_i / grad_j are the length-4 gradient vectors of
        players i and j at that optimization step, captured after backward()
        and before the gradients were reset to zero.
        """
        return self._grad_log


if __name__ == '__main__':
    model = RatingModel(1000)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    i, j = 17, 42

    # targets come in from a generated csv of the raw data (one row per matchup)
    targets = {
        "first_serve_pts_win_rate": 0.72,
        "second_serve_pts_win_rate": 0.52,
        "break_pts_save_rate": 0.63,
        "first_serve_in_rate": 0.61,
        "df_rate": 0.05,
        "ace_rate": 0.08,
        "return_pts_win_rate": 0.38,
        "winner_rate": 0.29,
        "unforced_error_rate": 0.20,
    }

    # tentatively equal weights on each component; tune per-target to make the
    # gradient updates comparably meaningful across the different predictions.
    weights = {key: 1.0 for key in RatingModel.PREDICTORS}

    p_i, p_j = model.update(i, j, targets, optimizer, weights)

    print(f'Updated parameters for Player {i}: {p_i}')
    print(f'Updated parameters for Player {j}: {p_j}')
