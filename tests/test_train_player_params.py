import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest

import torch

from train_player_params import RatingModel


class TestRatingModel(unittest.TestCase):
    def _make_model(self, n=4):
        return RatingModel(n)

    def test_update_returns_two_param_vectors(self):
        model = self._make_model()
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-2)
        targets = {k: 0.5 for k in RatingModel.PREDICTORS}

        p_i, p_j = model.update(0, 1, targets, optimizer)

        self.assertEqual(tuple(p_i.shape), (4,))
        self.assertEqual(tuple(p_j.shape), (4,))
        # returned vectors should be detached (safe to use outside the graph)
        self.assertFalse(p_i.requires_grad)
        self.assertFalse(p_j.requires_grad)

    def test_only_the_two_players_are_updated(self):
        model = self._make_model()
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-2)
        targets = {k: 0.4 for k in RatingModel.PREDICTORS}

        before = model.params.detach().clone()
        model.update(0, 1, targets, optimizer)
        after = model.params.detach()

        # players 0 and 1 changed...
        self.assertFalse(torch.allclose(after[0], before[0]))
        self.assertFalse(torch.allclose(after[1], before[1]))
        # ...uninvolved players did not.
        self.assertTrue(torch.allclose(after[2], before[2]))
        self.assertTrue(torch.allclose(after[3], before[3]))

    def test_optimizer_converges_to_reachable_targets(self):
        # Generate self-consistent targets from a KNOWN parameter set, so a
        # zero-loss solution provably exists, then check the optimizer finds it.
        model = self._make_model()
        i, j = 0, 1
        with torch.no_grad():
            model.params.data[i] = torch.tensor([6.0, 4.0, 5.5, 5.0])
            model.params.data[j] = torch.tensor([4.5, 6.0, 5.0, 4.0])
        targets = {k: getattr(model, k)(i, j).item() for k in RatingModel.PREDICTORS}

        # Reset to the default init and try to recover a low loss.
        with torch.no_grad():
            model.params.data.fill_(5.0)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-2)

        initial_loss = model.loss(i, j, targets).item()
        model.update(i, j, targets, optimizer, steps=3000)
        final_loss = model.loss(i, j, targets).item()

        self.assertLess(final_loss, initial_loss)
        self.assertLess(final_loss, 1e-5)
        for k in RatingModel.PREDICTORS:
            self.assertAlmostEqual(getattr(model, k)(i, j).item(), targets[k], places=3)


if __name__ == '__main__':
    unittest.main()
