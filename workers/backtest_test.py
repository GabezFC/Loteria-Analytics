"""Testes do backtest walk-forward: ausência de vazamento, reprodutibilidade, calibração e detecção de sinal plantado."""
import json
import unittest

import numpy as np

import backtest as B

POOL, K = 25, 15
PRIZES = (15, 14, 13, 12, 11)


def make_draws(n, seed, weights=None, pool=POOL, k=K):
    rng = np.random.default_rng(seed)
    w = None if weights is None else np.asarray(weights, float) / np.sum(weights)
    return np.array([np.sort(rng.choice(pool, k, replace=False, p=w) + 1) for _ in range(n)], dtype=np.int16)


def payouts_for(n, k=K):
    p = np.zeros((n, k + 1))
    for hits, v in zip(PRIZES, (1_000_000, 1500, 25, 10, 5)):
        p[:, hits] = v
    return p


def run(draws, models=("freq_all", "delay_overdue", "ridge_logit", "freq_w100"), tests=100, tickets=5, seeds=2, reps=50, refit=25, seed=7, progress=None):
    n = len(draws)
    return B.run_backtest(draws, np.arange(1, n + 1), POOL, K, 3.5, PRIZES, payouts_for(n), list(models), tests, tickets, seeds, reps, refit, seed, progress)


def by(res, model, metric):
    return next(r for r in res["results"] if r["model_name"] == model and r["metric_name"] == metric)


class HistoryTests(unittest.TestCase):
    def test_delays_handcrafted_and_causal(self):
        d = np.array([[1, 2], [1, 3], [1, 4], [2, 3]], dtype=np.int16)
        h = B.History.build(d, 4, 2)
        self.assertEqual(h.D[0].tolist(), [0, 0, 0, 0])      # nada visto: atraso = t
        self.assertEqual(h.D[1].tolist(), [0, 0, 1, 1])      # antes do concurso 1: 1,2 saíram no 0
        self.assertEqual(h.D[3].tolist(), [0, 2, 1, 0])      # antes do concurso 3
        self.assertEqual(h.C[3].tolist(), [3, 1, 1, 1])      # contagens dos 3 primeiros
        cnt, nw = h.freq(3, 2)
        self.assertEqual((cnt.tolist(), nw), ([2, 0, 1, 1], 2))


class NoLeakage(unittest.TestCase):
    def test_predictions_at_t_ignore_all_data_from_t_onward(self):
        n, cut = 400, 330
        base = make_draws(n, 1)
        perturbed = base.copy()
        perturbed[cut:] = make_draws(n - cut, 999, weights=np.arange(1, POOL + 1))   # futuro completamente diferente
        tests = np.arange(300, cut)
        for model in B.MODEL_CATALOG:
            a, _ = B.predict_matrix(B.History.build(base, POOL, K), model, tests, 25)
            b, _ = B.predict_matrix(B.History.build(perturbed, POOL, K), model, tests, 25)
            np.testing.assert_array_equal(a, b, err_msg=f"vazamento em {model}")

    def test_backtest_results_for_a_period_do_not_depend_on_later_draws(self):
        n_total, T = 420, 80
        base = make_draws(n_total, 5)
        late = base.copy()
        late[300:] = make_draws(n_total - 300, 77, weights=np.arange(1, POOL + 1))
        # backtest A termina em 300: usa apenas draws[:300] — idêntico nas duas bases
        a = run(base[:300], tests=T, reps=50)
        b = run(late[:300], tests=T, reps=50)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_ridge_refit_only_uses_past_labels(self):
        d = make_draws(350, 3)
        h = B.History.build(d, POOL, K)
        m1 = B.fit_ridge(h, 250)
        d2 = d.copy()
        d2[250:] = make_draws(100, 4, weights=np.arange(1, POOL + 1))
        m2 = B.fit_ridge(B.History.build(d2, POOL, K), 250)
        np.testing.assert_allclose(m1.w, m2.w)


class Reproducibility(unittest.TestCase):
    def test_same_seed_identical_different_seed_differs(self):
        d = make_draws(300, 11)
        a, b, c = run(d, seed=1), run(d, seed=1), run(d, seed=2)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertNotEqual(by(a, "freq_all", "mean_hits_per_ticket")["value"], by(c, "freq_all", "mean_hits_per_ticket")["value"])
        json.dumps(a, allow_nan=False)  # serializável

    def test_progress_callback_reaches_total(self):
        calls = []
        run(make_draws(260, 2), models=("freq_all",), tests=60, reps=50, progress=lambda a, b, s: calls.append((a, b)))
        self.assertTrue(calls)
        self.assertEqual(calls[-1][0], calls[-1][1])


class Validation(unittest.TestCase):
    def test_parameter_limits(self):
        d = make_draws(300, 1)
        bad = [dict(tests=20), dict(tests=100, tickets=51), dict(tests=100, seeds=0), dict(tests=100, reps=10), dict(tests=100, refit=5), dict(tests=290)]
        for kw in bad:
            with self.assertRaises(ValueError, msg=str(kw)):
                run(d, models=("freq_all",), **kw)
        with self.assertRaises(ValueError):
            run(d, models=("nao_existe",))
        with self.assertRaises(ValueError):
            B.run_backtest(d, np.arange(1, 301), POOL, K, 3.5, PRIZES, payouts_for(300), ["freq_all"], 1000, 50, 2, 50, 25, 1)  # 50.000 linhas


class Statistics(unittest.TestCase):
    def test_verdict_rules(self):
        v = B.verdict_for
        self.assertEqual(v(1.2, 0.9, 1.0, 0.001, 0.01, (0.01, 0.02), True), "better_replicated")
        self.assertEqual(v(1.2, 0.9, 1.0, 0.001, 0.01, (0.01, 0.4), True), "better_significant_not_replicated")
        self.assertEqual(v(1.2, 0.9, 1.0, 0.2, 0.4, (0.3, 0.4), True), "better_not_significant")
        self.assertEqual(v(0.8, 0.9, 1.0, 0.9, 0.9, (0.9, 0.9), True), "worse_than_baseline")
        self.assertEqual(v(0.95, 0.9, 1.0, 0.5, 0.6, (0.5, 0.5), True), "indistinguishable")
        self.assertEqual(v(0.4, 0.5, 0.6, 0.001, 0.01, (0.01, 0.01), False), "better_replicated")  # menor é melhor
        self.assertEqual(v(0.7, 0.5, 0.6, 0.9, 0.9, (0.9, 0.9), False), "worse_than_baseline")

    def test_sample_tickets_are_valid_and_follow_weights(self):
        rng = np.random.default_rng(0)
        w = np.ones((2000, POOL))
        w[:, 0] = 6.0
        t = B.sample_tickets(w, 3, K, rng)
        self.assertEqual(t.shape, (2000, 3, K))
        self.assertTrue(all(len(set(x)) == K for x in t.reshape(-1, K)[:500]))
        share0 = (t == 0).any(axis=2).mean()
        self.assertGreater(share0, K / POOL + 0.1)   # número 1 sobre-representado
        u = B.sample_tickets(np.ones((4000, POOL)), 1, K, np.random.default_rng(1))
        self.assertAlmostEqual((u == 0).any(axis=2).mean(), K / POOL, delta=0.03)

    def test_uniform_data_gives_no_replicated_advantage_and_losses_not_better(self):
        replicated = 0
        for s in range(5):
            res = run(make_draws(400, 100 + s), tests=120, reps=100, seeds=2, seed=s)
            replicated += sum(r["verdict"] == "better_replicated" for r in res["results"])
            self.assertIn(res["conclusion"]["verdict"], ("no_evidence_of_advantage", "inconclusive"))
            for m in ("freq_all", "freq_w100", "ridge_logit"):
                ll = by(res, m, "log_loss")
                self.assertGreaterEqual(ll["value"], ll["baseline_value"] - 3e-3)  # sem sinal, não supera a uniforme
        self.assertEqual(replicated, 0)

    def test_planted_signal_is_detected(self):
        w = np.ones(POOL)
        w[:6] = 5.0                                   # seis dezenas muito mais prováveis
        res = run(make_draws(450, 8, weights=w), tests=150, tickets=10, reps=200, seeds=3, seed=3)
        for m in ("freq_all", "freq_w100", "ridge_logit"):
            hits = by(res, m, "mean_hits_per_ticket")
            self.assertGreater(hits["value"], hits["baseline_ci_high"], m)
            self.assertLess(hits["p_value"], 0.01, m)
            self.assertIn(hits["verdict"], ("better_replicated", "better_significant_not_replicated"), m)
            ll = by(res, m, "log_loss")
            self.assertLess(ll["value"], ll["baseline_value"], m)
            self.assertLess(ll["p_value"], 0.001, m)
        self.assertEqual(res["conclusion"]["verdict"], "candidate_advantage_needs_replication")
        ridge_info = res["meta"]["model_info"]["ridge_logit"]
        self.assertIn("standardized_coefficients", ridge_info)

    def test_non_probabilistic_model_has_no_loss_metrics_and_structure(self):
        res = run(make_draws(300, 4), models=("delay_overdue",), tests=60)
        self.assertEqual({r["metric_name"] for r in res["results"]}, {"mean_hits_per_ticket", "tier_hit_rate", "return_ratio"})
        r = by(res, "delay_overdue", "mean_hits_per_ticket")
        self.assertEqual(r["payload"]["hits_distribution"]["values"], list(range(K + 1)))
        self.assertAlmostEqual(sum(r["payload"]["hits_distribution"]["expected"]), 1.0)
        self.assertLess(r["q_value"] + 1e-12, 1.0 + 1e-9)
        self.assertEqual(res["meta"]["n_hypotheses"], 3)
        self.assertEqual(res["meta"]["test_end_contest"], 300)
        self.assertEqual(res["meta"]["train_cutoff_contest"], 240)

    def test_return_ratio_uses_historical_payouts_and_cost(self):
        # prêmios iguais a 0 => retorno 0 em todos os modelos e no baseline
        d = make_draws(260, 6)
        n = len(d)
        res = B.run_backtest(d, np.arange(1, n + 1), POOL, K, 3.5, PRIZES, np.zeros((n, K + 1)), ["freq_all"], 60, 5, 2, 50, 25, 1)
        rr = by(res, "freq_all", "return_ratio")
        self.assertEqual((rr["value"], rr["baseline_value"]), (0.0, 0.0))
        # retorno ≈ faixa premiada x prêmio / custo: com prêmio 3.5 em 11 acertos o retorno do baseline fica em torno de P(11+)·3.5/3.5
        pay = np.zeros((n, K + 1))
        pay[:, 11:] = 3.5
        res2 = B.run_backtest(d, np.arange(1, n + 1), POOL, K, 3.5, PRIZES, pay, ["freq_all"], 60, 5, 2, 100, 25, 1)
        from probabilities import at_least_probability
        expect = float(at_least_probability(POOL, K, K, 11))
        self.assertAlmostEqual(by(res2, "freq_all", "return_ratio")["baseline_value"], expect, delta=0.06)


if __name__ == "__main__":
    unittest.main()
