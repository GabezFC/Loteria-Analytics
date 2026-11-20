"""Testes offline dos cálculos exatos (probabilities) e do motor estatístico (stats)."""
import unittest
from fractions import Fraction
from math import comb

import numpy as np

import probabilities as P
import stats as S

MEGA, LOTO, QUINA = (60, 6), (25, 15), (80, 5)


def random_draws(n, pool, k, seed, weights=None):
    rng = np.random.default_rng(seed)
    out = np.empty((n, k), dtype=np.int16)
    w = None if weights is None else np.asarray(weights, dtype=float) / np.sum(weights)
    for i in range(n):
        out[i] = np.sort(rng.choice(pool, size=k, replace=False, p=w) + 1)
    return out


class ExactProbabilityTests(unittest.TestCase):
    def test_total_combinations_match_specification(self):
        self.assertEqual(P.combinations_total(*MEGA), 50_063_860)
        self.assertEqual(P.combinations_total(*LOTO), 3_268_760)
        self.assertEqual(P.combinations_total(*QUINA), 24_040_016)

    def test_official_odds_simple_bet(self):
        odds = lambda pool_k, hits: round(1 / float(P.hits_probability(*pool_k, pool_k[1], hits)))
        self.assertEqual(odds(MEGA, 6), 50_063_860)
        self.assertEqual(odds(MEGA, 5), 154_518)
        self.assertEqual(odds(MEGA, 4), 2_332)
        self.assertEqual(odds(LOTO, 15), 3_268_760)
        self.assertEqual(odds(LOTO, 14), 21_792)
        self.assertEqual(odds(LOTO, 13), 692)
        self.assertEqual(odds(LOTO, 12), 60)
        self.assertEqual(odds(LOTO, 11), 11)
        self.assertEqual(odds(QUINA, 5), 24_040_016)
        self.assertEqual(odds(QUINA, 4), 64_107)
        self.assertEqual(odds(QUINA, 3), 866)
        self.assertEqual(odds(QUINA, 2), 36)

    def test_distribution_sums_to_one_for_every_bet_size(self):
        for (pool, k), hi in ((MEGA, 20), (LOTO, 20), (QUINA, 15)):
            for b in range(k, hi + 1):
                self.assertEqual(sum(P.hits_probability(pool, k, b, r) for r in range(k + 1)), 1)

    def test_multiple_bet_jackpot_equals_games_over_total(self):
        # Mega com 7 dezenas = 7 jogos simples distintos
        self.assertEqual(P.hits_probability(60, 6, 7, 6), Fraction(7, 50_063_860))
        self.assertEqual(P.simple_games(6, 7), 7)
        self.assertEqual(P.simple_games(6, 20), 38_760)
        self.assertEqual(P.simple_games(5, 15), 3_003)
        self.assertEqual(P.hits_probability(80, 5, 15, 5), Fraction(3003, 24_040_016))

    def test_games_with_hits_counts_sub_tickets(self):
        # Mega 7 dezenas, 5 sorteadas dentro: C(5,4)*C(2,2) = 5 jogos com quadra
        self.assertEqual(P.games_with_hits(6, 7, 5, 4), comb(5, 4) * comb(2, 2))

    def test_tickets_and_contests(self):
        self.assertEqual(P.jackpot_with_tickets(60, 6, 10), Fraction(10, 50_063_860))
        self.assertEqual(P.jackpot_with_tickets(60, 6, 1, 2), 1 - (1 - Fraction(1, 50_063_860)) ** 2)
        with self.assertRaises(ValueError):
            P.jackpot_with_tickets(25, 15, 3_268_761)

    def test_at_least_is_tail_sum_and_invalid_inputs(self):
        self.assertEqual(P.at_least_probability(80, 5, 5, 4), P.hits_probability(80, 5, 5, 4) + P.hits_probability(80, 5, 5, 5))
        with self.assertRaises(ValueError):
            P.hits_probability(80, 5, 4, 2)  # aposta menor que k
        with self.assertRaises(ValueError):
            P.combinations_total(5, 6)

    def test_any_specific_set_has_same_probability(self):
        self.assertEqual(P.hits_probability(60, 6, 6, 6), Fraction(1, comb(60, 6)))


class StatsHelpers(unittest.TestCase):
    def test_benjamini_hochberg_known_example(self):
        p = np.array([0.01, 0.04, 0.03, 0.005])
        q = S.benjamini_hochberg(p)
        np.testing.assert_allclose(q, [0.02, 0.04, 0.04, 0.02])

    def test_bh_with_unobserved_tests_is_conservative(self):
        p = np.array([0.001])
        self.assertAlmostEqual(float(S.benjamini_hochberg(p, 100)[0]), 0.1)

    def test_wilson_interval_contains_estimate(self):
        lo, hi = S.wilson(np.array([10, 0, 100]), 100)
        self.assertTrue(np.all(lo <= np.array([0.1, 0.0, 1.0]) + 1e-12) and np.all(hi >= np.array([0.1, 0.0, 1.0]) - 1e-12))
        self.assertTrue(np.all(lo >= 0) and np.all(hi <= 1))

    def test_gof_merges_small_classes(self):
        r = S.gof(np.array([50, 30, 2, 1]), np.array([48, 31, 3, 1]))
        self.assertIsNotNone(r["p_value"])
        self.assertGreater(r["p_value"], 0.5)


class NumberStatsTests(unittest.TestCase):
    def test_delays_and_frequency_handcrafted(self):
        # k=2, N=4: série 1:{1,2} 2:{1,3} 3:{1,4} 4:{2,3}
        draws = np.array([[1, 2], [1, 3], [1, 4], [2, 3]], dtype=np.int16)
        m = S.indicator(draws, 4)
        st = {r["number"]: r for r in S.number_stats(m, 4, 2)}
        self.assertEqual(st[1]["frequency"], 3)
        self.assertEqual(st[1]["current_delay"], 1)      # ausente no último concurso
        self.assertEqual(st[1]["max_delay"], 1)
        self.assertEqual(st[2]["current_delay"], 0)
        self.assertEqual(st[2]["max_delay"], 2)          # ausente nos concursos 2 e 3
        self.assertEqual(st[4]["frequency"], 1)
        self.assertEqual(st[4]["current_delay"], 1)
        self.assertEqual(st[4]["max_delay"], 2)          # ausente 0,1 (borda inicial) -> 2
        self.assertAlmostEqual(st[1]["expected_frequency"], 4 * 0.5)
        self.assertIsNone(st[4]["mean_gap"])
        self.assertAlmostEqual(st[1]["mean_gap"], 1.0)


class InferenceCalibration(unittest.TestCase):
    def test_uniform_data_is_not_rejected_and_pvalues_are_calibrated(self):
        pvals = []
        for seed in range(30):
            d = random_draws(300, 25, 15, seed)
            res = S.analyze_window(np.arange(1, 301), d, 25, 15, seed=seed, sims=100, perms=60)
            pvals.append(res["inference"]["chi_square_uniformity"]["p_value_asymptotic"])
        pvals = np.array(pvals)
        self.assertLess((pvals < 0.05).mean(), 0.2)         # ~5% esperado
        self.assertGreater(pvals.mean(), 0.35)
        self.assertLess(pvals.mean(), 0.65)

    def test_biased_data_is_rejected(self):
        w = np.ones(25)
        w[0] = 4.0
        d = random_draws(600, 25, 15, 1, weights=w)
        res = S.analyze_window(np.arange(1, 601), d, 25, 15, seed=7, sims=100, perms=60)
        chi = res["inference"]["chi_square_uniformity"]
        self.assertLess(chi["p_value_asymptotic"], 1e-6)
        self.assertLess(chi["p_value_monte_carlo"], 0.05)
        nums = {r["number"]: r for r in res["number_stats"]}
        self.assertGreater(nums[1]["z_score"], 5)

    def test_temporal_dependence_is_detected(self):
        rng = np.random.default_rng(3)
        rows = []
        prev = None
        for _ in range(500):  # cada concurso repete 10 dezenas do anterior: dependência forte
            base = rng.choice(25, 15, replace=False) if prev is None else np.concatenate((rng.choice(prev, 10, replace=False), []))
            if prev is not None:
                rest = np.setdiff1d(np.arange(25), base)
                base = np.concatenate((base, rng.choice(rest, 5, replace=False)))
            prev = base
            rows.append(np.sort(base) + 1)
        d = np.array(rows, dtype=np.int16)
        res = S.analyze_window(np.arange(1, 501), d, 25, 15, seed=1, sims=50, perms=80)
        ac = res["inference"]["autocorrelation_lag1"]
        self.assertLess(ac["p_value_permutation_max_abs_z"], 0.05)
        self.assertGreater(ac["significant_q05"], 5)

    def test_reproducible_with_same_seed_and_differs_with_other(self):
        d = random_draws(200, 25, 15, 9)
        c = np.arange(1, 201)
        a = S.analyze_window(c, d, 25, 15, seed=5, sims=60, perms=40)
        b = S.analyze_window(c, d, 25, 15, seed=5, sims=60, perms=40)
        self.assertEqual(a, b)
        z = S.analyze_window(c, d, 25, 15, seed=6, sims=60, perms=40)
        self.assertNotEqual(a["inference"]["entropy"]["p_value_lower_tail"], z["inference"]["entropy"]["p_value_lower_tail"])
        self.assertEqual(a["number_stats"], z["number_stats"])  # parte determinística independe da semente

    def test_small_window_skips_inference_and_combinations(self):
        d = random_draws(30, 60, 6, 2)
        res = S.analyze_window(np.arange(1, 31), d, 60, 6, seed=1)
        self.assertIsNone(res["inference"])
        self.assertEqual(res["combinations"], [])
        self.assertFalse(res["meta"]["inference_available"])

    def test_distributions_match_theory_on_uniform_data(self):
        d = random_draws(2000, 60, 6, 4)
        res = S.analyze_window(np.arange(1, 2001), d, 60, 6, seed=1, sims=20, perms=20)
        dist = res["distributions"]
        self.assertAlmostEqual(dist["sum"]["mean"], dist["sum"]["expected_mean"], delta=4)
        self.assertAlmostEqual(dist["consecutive"]["mean"], dist["consecutive"]["expected_mean"], delta=0.05)
        self.assertGreater(dist["parity"]["evens_per_draw"]["gof"]["p_value"], 0.001)
        self.assertAlmostEqual(dist["repeated_from_previous"]["mean"], dist["repeated_from_previous"]["expected_mean"], delta=0.05)
        meta = res["combination_meta"]["sizes"]
        self.assertEqual(meta["2"]["possible"], comb(60, 2))
        # sob H0 poucos pares significativos após BH
        self.assertLessEqual(meta["2"]["significant_q05"], 3)
        pairs = [c for c in res["combinations"] if c["combo_size"] == 2]
        self.assertTrue(all(c["numbers"] == sorted(c["numbers"]) for c in pairs))

    def test_fingerprint_changes_when_data_changes(self):
        d = random_draws(10, 25, 15, 1)
        c = np.arange(1, 11)
        f1 = S.fingerprint(c, d)
        d2 = d.copy()
        d2[0, 0] = 1 if d2[0, 0] != 1 else 2
        self.assertNotEqual(f1, S.fingerprint(c, np.sort(d2, axis=1)))
        self.assertEqual(f1, S.fingerprint(c, d.copy()))


if __name__ == "__main__":
    unittest.main()
