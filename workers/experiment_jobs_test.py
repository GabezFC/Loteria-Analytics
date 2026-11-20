"""Testes de sugestões (offline) e dos jobs de experimento/sugestão (integração com banco descartável)."""
import math
import os
import threading
import unittest

import numpy as np

import backtest as B
import suggestions as S

SKIP = not (os.environ.get("PGHOST") and os.environ.get("TEST_ADMIN_DSN"))


def history(n=300, pool=25, k=15, seed=1):
    rng = np.random.default_rng(seed)
    d = np.array([np.sort(rng.choice(pool, k, replace=False) + 1) for _ in range(n)], dtype=np.int16)
    return B.History.build(d, pool, k), d


class SuggestionTests(unittest.TestCase):
    def test_all_strategies_produce_distinct_valid_tickets_and_bounded_scores(self):
        h, _ = history()
        for strat in S.STRATEGIES:
            out = S.generate(strat, h, 25, 15, 12, seed=3)
            self.assertEqual(len(out), 12)
            tickets = [tuple(t) for t, _ in out]
            self.assertEqual(len(set(tickets)), 12, strat)
            for t, score in out:
                self.assertEqual(len(set(t)), 15)
                self.assertTrue(all(1 <= x <= 25 for x in t) and t == sorted(t))
                self.assertTrue(0.0 <= score <= 1.0)

    def test_reproducible_by_seed(self):
        h, _ = history()
        self.assertEqual(S.generate("frequency_weighted", h, 25, 15, 5, 9), S.generate("frequency_weighted", h, 25, 15, 5, 9))
        self.assertNotEqual(S.generate("uniform_random", None, 25, 15, 5, 1), S.generate("uniform_random", None, 25, 15, 5, 2))

    def test_diversity_overlaps_less_than_uniform(self):
        def mean_overlap(tickets):
            sets = [set(t) for t, _ in tickets]
            return np.mean([len(sets[i] & sets[j]) for i in range(len(sets)) for j in range(i)])
        u = np.mean([mean_overlap(S.generate("uniform_random", None, 60, 6, 10, s)) for s in range(10)])
        d = np.mean([mean_overlap(S.generate("diversity", None, 60, 6, 10, s)) for s in range(10)])
        self.assertLess(d, u)

    def test_uniform_score_is_neutral_and_interpretation_denies_probability(self):
        out = S.generate("uniform_random", None, 80, 5, 3, 1)
        self.assertTrue(all(s == 0.5 for _, s in out))
        for text in S.INTERPRETATION.values():
            self.assertIn("não é probabilidade", text.lower())

    def test_errors(self):
        with self.assertRaises(ValueError):
            S.generate("magia", None, 25, 15, 1, 1)
        with self.assertRaises(ValueError):
            S.generate("uniform_random", None, 25, 15, 201, 1)
        with self.assertRaises(ValueError):
            S.generate("frequency_weighted", None, 25, 15, 1, 1)  # sem histórico
        with self.assertRaises(ValueError):
            S.generate("uniform_random", None, 5, 5, 2, 1)  # só 1 combinação possível

    def test_weighted_strategy_follows_weights_on_average(self):
        rng = np.random.default_rng(0)
        d = np.array([np.sort(rng.choice(25, 15, replace=False, p=np.r_[np.full(5, 0.12), np.full(20, 0.02)]) + 1) for _ in range(400)], dtype=np.int16)
        h = B.History.build(d, 25, 15)
        tickets = S.generate("frequency_weighted", h, 25, 15, 150, 4)
        share_hot = np.mean([sum(1 for x in t if x <= 5) for t, _ in tickets])
        self.assertGreater(share_hot, 15 * 5 / 25 + 0.3)


@unittest.skipIf(SKIP, "requer PGHOST e TEST_ADMIN_DSN de banco descartável")
class ExperimentJobsIntegration(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.admin = psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True)
        for t in ("suggestion", "suggestion_set", "experiment_result", "experiment", "number_stat", "combination_stat", "analysis_result", "analysis_run", "job",
                  "draw_extra", "draw_prize_tier", "draw_number", "ingest_draw_change", "lottery_draw"):
            self.admin.execute(f"DELETE FROM {t}")
        self.conn = psycopg.connect(autocommit=True)
        rng = np.random.default_rng(5)
        for c in range(1, 421):
            nums = sorted((rng.choice(25, 15, replace=False) + 1).tolist())
            did = self.admin.execute("INSERT INTO lottery_draw(lottery_slug,contest,draw_date,source_sha256) VALUES ('lotofacil',%s,date '2020-01-01' + %s::int,%s) RETURNING draw_id", (c, c, "0" * 64)).fetchone()[0]
            with self.admin.cursor() as cur:
                cur.executemany("INSERT INTO draw_number(draw_id,number) VALUES (%s,%s)", [(did, x) for x in nums])
                cur.executemany("INSERT INTO draw_prize_tier(draw_id,hits,winners,payout_amount) VALUES (%s,%s,%s,%s)", [(did, 15, 0, 0), (did, 14, 100, 1500), (did, 13, 3000, 25), (did, 12, 40000, 10), (did, 11, 300000, 5)])

    def tearDown(self):
        self.conn.close()
        self.admin.close()

    def enqueue_experiment(self, cfg, kind="backtest", seed=11):
        import json
        eid = self.admin.execute("INSERT INTO experiment(kind,lottery_slug,config,config_hash,seed) VALUES (%s,'lotofacil',%s::jsonb,md5(%s),%s) RETURNING experiment_id", (kind, json.dumps(cfg), json.dumps(cfg), seed)).fetchone()[0]
        self.admin.execute("INSERT INTO job(kind,lottery_slug,params) VALUES ('experiment','lotofacil',%s::jsonb)", (json.dumps({"experiment_id": eid}),))
        return eid

    def process(self):
        import analisador
        import experiment_jobs  # noqa: F401
        return analisador.process_pending(self.conn, threading.Event())

    def test_backtest_job_persists_results_conclusion_and_is_reproducible(self):
        cfg = dict(models=["freq_all", "ridge_logit", "delay_overdue"], test_contests=60, tickets_per_contest=3, seeds=2, baseline_replicates=50, refit_every=20)
        e1 = self.enqueue_experiment(cfg)
        self.assertEqual(self.process(), 1)
        row = self.conn.execute("select status, train_cutoff_contest, test_start_contest, test_end_contest, n_hypotheses, conclusion->>'verdict', progress->>'stage', data_fingerprint from experiment where experiment_id=%s", (e1,)).fetchone()
        self.assertEqual(row[0], "succeeded", row)
        self.assertEqual((row[1], row[2], row[3]), (360, 361, 420))
        self.assertEqual(row[4], 3 + 5 + 5)  # delay: 3 métricas; freq_all/ridge: 5 cada
        self.assertIn(row[5], ("no_evidence_of_advantage", "inconclusive"))
        self.assertEqual(row[6], "concluído")
        n_res = self.conn.execute("select count(*) from experiment_result where experiment_id=%s", (e1,)).fetchone()[0]
        self.assertEqual(n_res, 13)
        bad = self.conn.execute("select count(*) from experiment_result where experiment_id=%s and (verdict is null or q_value is null or p_value is null)", (e1,)).fetchone()[0]
        self.assertEqual(bad, 0)
        # mesma semente e dados => mesmos resultados
        e2 = self.enqueue_experiment(cfg)
        self.process()
        q = "select model_name, metric_name, value, p_value, verdict from experiment_result where experiment_id=%s order by 1,2"
        self.assertEqual(self.conn.execute(q, (e1,)).fetchall(), self.conn.execute(q, (e2,)).fetchall())
        # progresso observável vira job succeeded
        self.assertEqual(self.conn.execute("select count(*) from job where kind='experiment' and status='succeeded'").fetchone()[0], 2)

    def test_backtest_failure_is_recorded(self):
        e = self.enqueue_experiment(dict(models=["freq_all"], test_contests=2000, tickets_per_contest=5, seeds=2, baseline_replicates=50, refit_every=20))
        self.process()
        st, err = self.conn.execute("select status, error from experiment where experiment_id=%s", (e,)).fetchone()
        self.assertEqual(st, "failed")
        self.assertIn("histórico insuficiente", err)
        self.assertEqual(self.conn.execute("select status from job where kind='experiment'").fetchone()[0], "failed")

    def test_suggestion_job_persists_tickets_with_exact_probability(self):
        sid = self.admin.execute("INSERT INTO suggestion_set(lottery_slug,strategy,seed,ticket_count) VALUES ('lotofacil','frequency_weighted',5,4) RETURNING set_id").fetchone()[0]
        self.admin.execute("INSERT INTO job(kind,lottery_slug,params) VALUES ('suggestion','lotofacil',jsonb_build_object('set_id',%s::bigint))", (sid,))
        self.process()
        st, based, cost = self.conn.execute("select status, based_on_contest, total_cost from suggestion_set where set_id=%s", (sid,)).fetchone()
        self.assertEqual((st, based, float(cost)), ("succeeded", 420, 14.0))
        rows = self.conn.execute("select numbers, heuristic_score, jackpot_numerator, jackpot_denominator from suggestion where set_id=%s order by position", (sid,)).fetchall()
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(int(r[2]) == 1 and int(r[3]) == math.comb(25, 15) and len(r[0]) == 15 and 0 <= r[1] <= 1 for r in rows))
        self.assertEqual(len({tuple(r[0]) for r in rows}), 4)

    def test_suggestion_links_backtest_evidence_when_available(self):
        self.enqueue_experiment(dict(models=["freq_w100"], test_contests=60, tickets_per_contest=3, seeds=2, baseline_replicates=50, refit_every=20))
        self.process()
        sid = self.admin.execute("INSERT INTO suggestion_set(lottery_slug,strategy,seed,ticket_count) VALUES ('lotofacil','frequency_weighted',5,2) RETURNING set_id").fetchone()[0]
        self.admin.execute("INSERT INTO job(kind,lottery_slug,params) VALUES ('suggestion','lotofacil',jsonb_build_object('set_id',%s::bigint))", (sid,))
        self.process()
        ev = self.conn.execute("select evidence->>'model_name', evidence->>'verdict' from suggestion_set where set_id=%s", (sid,)).fetchone()
        self.assertEqual(ev[0], "freq_w100")
        self.assertIsNotNone(ev[1])


if __name__ == "__main__":
    unittest.main()
