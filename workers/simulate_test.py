import json
import time
import unittest
from fractions import Fraction
from math import comb

import numpy as np

import simulate as M

MEGA = dict(pool=60, draw=6, simple_price=6.0, prize_hits=(6, 5, 4))
PAY = {5: 50_000.0, 4: 1_000.0}


def run(tickets=5, contests=100, replicates=100, seed=1, payouts=None, **kw):
    return M.run_montecarlo(MEGA["pool"], MEGA["draw"], tickets, contests, replicates, seed, MEGA["simple_price"], PAY if payouts is None else payouts, MEGA["prize_hits"], **kw)


class MonteCarloTests(unittest.TestCase):
    def test_reproducible_and_seed_sensitive_and_json_safe(self):
        a, b, c = run(seed=4), run(seed=4), run(seed=5)
        self.assertEqual(a, b)
        self.assertNotEqual(a["hits_distribution"]["observed_share"], c["hits_distribution"]["observed_share"])
        json.dumps(a, allow_nan=False)

    def test_validations(self):
        bad = [dict(tickets=0), dict(contests=0), dict(contests=5001), dict(replicates=9), dict(replicates=2001),
               dict(tickets=comb(60, 6) + 1), dict(contests=5000, replicates=2000), dict(payouts={9: 1.0}), dict(payouts={5: -1.0})]
        for kw in bad:
            with self.assertRaises(ValueError, msg=str(kw)):
                run(**kw)
        with self.assertRaises(ValueError):
            M.run_montecarlo(60, 0, 1, 10, 10, 1, 6.0, {}, (6,))
        with self.assertRaises(ValueError):
            M.run_montecarlo(60, 6, 1, 10, 10, 1, -6.0, {}, (6,))

    def test_shapes_and_monotone_percentiles(self):
        r = run(contests=200, replicates=200, checkpoints=20)
        npaths = r["net_result_paths"]
        n = len(npaths["checkpoints"])
        self.assertEqual(npaths["checkpoints"][-1], 200)
        self.assertLessEqual(n, 20)
        self.assertEqual(len(npaths["cost_curve"]), n)
        keys = ["5", "25", "50", "75", "95"]
        self.assertEqual(list(npaths["percentiles"]), keys)
        for i in range(n):
            vals = [npaths["percentiles"][k][i] for k in keys]
            self.assertEqual(vals, sorted(vals))
        self.assertAlmostEqual(npaths["cost_curve"][-1], 5 * 200 * 6.0)
        fd = r["final_net_distribution"]
        self.assertEqual(len(fd["edges"]), len(fd["counts"]) + 1)
        self.assertEqual(sum(fd["counts"]), 200)
        self.assertEqual(r["total_cost"], 5 * 200 * 6.0)

    def test_jackpot_probability_exact(self):
        self.assertEqual(Fraction(*(int(x) for x in (run(tickets=1, contests=1)["jackpot_probability"]["numerator"], run(tickets=1, contests=1)["jackpot_probability"]["denominator"]))), Fraction(1, 50_063_860))
        j = run(tickets=10, contests=3)["jackpot_probability"]
        exact = 1 - (1 - Fraction(10, 50_063_860)) ** 3
        self.assertEqual(Fraction(int(j["numerator"]), int(j["denominator"])), exact)
        self.assertAlmostEqual(j["value"], float(exact), places=18)

    def test_hits_distribution_matches_theory(self):
        r = run(tickets=20, contests=500, replicates=100, seed=2)
        h = r["hits_distribution"]
        self.assertAlmostEqual(sum(h["expected_share"]), 1.0)
        self.assertAlmostEqual(sum(h["observed_share"]), 1.0)
        mean = sum(v * s for v, s in zip(h["values"], h["observed_share"]))
        self.assertAlmostEqual(mean, 36 / 60, delta=0.01)  # k²/N
        self.assertEqual(h["tickets_total"], 20 * 500 * 100)

    def test_gof_p_values_are_calibrated(self):
        ps = np.array([run(tickets=10, contests=200, replicates=50, seed=s)["hits_distribution"]["gof_p_value"] for s in range(30)])
        self.assertLess((ps < 0.05).mean(), 0.2)
        self.assertTrue(0.3 < ps.mean() < 0.7, ps.mean())

    def test_zero_prizes_means_total_loss(self):
        r = run(payouts={5: 0.0, 4: 0.0})
        fd = r["final_net_distribution"]
        self.assertEqual(fd["share_total_loss"], 1.0)
        self.assertEqual(fd["share_positive"], 0.0)
        self.assertAlmostEqual(fd["mean"], -5 * 100 * 6.0)

    def test_common_tier_prize_raises_positive_share_and_jackpot_never_pays(self):
        base = run(tickets=20, contests=100, replicates=200, payouts={4: 6.0}, seed=3)
        rich = run(tickets=20, contests=100, replicates=200, payouts={4: 5_000.0}, seed=3)
        self.assertGreater(rich["final_net_distribution"]["share_positive"], base["final_net_distribution"]["share_positive"])
        jackpot_only = run(tickets=20, contests=100, replicates=200, payouts={6: 1e12}, seed=3)
        self.assertEqual(jackpot_only["final_net_distribution"]["share_positive"], 0.0)
        self.assertEqual(jackpot_only["final_net_distribution"]["share_total_loss"], 1.0)

    def test_limitations_mention_jackpot_assumption_and_performance(self):
        r = run()
        self.assertTrue(any("principal" in s for s in r["limitations"]))
        t0 = time.time()
        run(tickets=10, contests=2000, replicates=500, seed=1)
        self.assertLess(time.time() - t0, 30)


if __name__ == "__main__":
    unittest.main()
