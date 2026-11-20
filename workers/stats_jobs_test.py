"""Integração (banco descartável): probability_table e jobs de estatística, idempotência e invalidação."""
import os
import threading
import unittest

import numpy as np

SKIP = not (os.environ.get("PGHOST") and os.environ.get("TEST_ADMIN_DSN"))


def seed_draws(admin, n, start=1, slug="lotofacil", pool=25, k=15, seed=1):
    rng = np.random.default_rng(seed)
    for c in range(start, start + n):
        nums = sorted((rng.choice(pool, k, replace=False) + 1).tolist())
        did = admin.execute(
            "INSERT INTO lottery_draw(lottery_slug,contest,draw_date,source_sha256) VALUES (%s,%s,date '2020-01-01' + %s::int,%s) RETURNING draw_id",
            (slug, c, c, "0" * 64),
        ).fetchone()[0]
        with admin.cursor() as cur:
            cur.executemany("INSERT INTO draw_number(draw_id,number) VALUES (%s,%s)", [(did, x) for x in nums])


@unittest.skipIf(SKIP, "requer PGHOST e TEST_ADMIN_DSN de banco descartável")
class StatsJobsIntegration(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.admin = psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True)
        for t in ("number_stat", "combination_stat", "analysis_result", "analysis_run", "job", "ingest_draw_change", "draw_number", "lottery_draw"):
            self.admin.execute(f"DELETE FROM {t}")
        self.conn = psycopg.connect(autocommit=True)

    def tearDown(self):
        self.conn.close()
        self.admin.close()

    def test_probability_table_is_exact_and_idempotent(self):
        import stats_jobs
        n1 = stats_jobs.ensure_probability_table(self.conn)
        n2 = stats_jobs.ensure_probability_table(self.conn)
        self.assertEqual(n1, n2)
        row = self.conn.execute("select exact_numerator, exact_denominator, is_prize_tier, cost from probability_table where lottery_slug='megasena' and bet_size=7 and hits=6").fetchone()
        self.assertEqual((int(row[0]), int(row[1]), row[2], float(row[3])), (7, 50_063_860, True, 42.0))
        total = self.conn.execute("select sum(exact_numerator) = max(exact_denominator) from probability_table where lottery_slug='quina' and bet_size=9").fetchone()[0]
        self.assertTrue(total)  # soma das faixas = C(N,k)
        rows = self.conn.execute("select count(*) from probability_table").fetchone()[0]
        self.assertEqual(rows, 15 * 7 + 6 * 16 + 11 * 6)

    def test_analyze_computes_windows_once_and_recomputes_on_new_data(self):
        import analisador
        import stats_jobs  # noqa: F401  (registra o handler)
        import common
        seed_draws(self.admin, 320)
        self.admin.execute("INSERT INTO job(kind, lottery_slug) VALUES ('analyze','lotofacil')")
        self.assertEqual(analisador.process_pending(self.conn, threading.Event()), 1)
        runs = self.conn.execute("select window_label, sample_size, status from analysis_run order by sample_size").fetchall()
        self.assertEqual([r[0] for r in runs], ["30", "100", "300", "all"])  # 1000 ignorada: < 1000 concursos
        self.assertTrue(all(r[2] == "succeeded" for r in runs))
        full = self.conn.execute("select analysis_run_id from analysis_run where window_label='all'").fetchone()[0]
        self.assertEqual(self.conn.execute("select count(*) from number_stat where analysis_run_id=%s", (full,)).fetchone()[0], 25)
        kinds = {r[0] for r in self.conn.execute("select kind from analysis_result where analysis_run_id=%s", (full,)).fetchall()}
        self.assertTrue({"distributions", "inference", "meta", "combination_meta"} <= kinds)
        self.assertGreater(self.conn.execute("select count(*) from combination_stat where analysis_run_id=%s", (full,)).fetchone()[0], 0)
        # Sem dados novos: tudo em cache, nenhuma linha nova
        self.admin.execute("INSERT INTO job(kind, lottery_slug) VALUES ('analyze','lotofacil')")
        analisador.process_pending(self.conn, threading.Event())
        self.assertEqual(self.conn.execute("select count(*) from analysis_run").fetchone()[0], 4)
        # Novo concurso: janelas deslizam e são recalculadas (fingerprint muda)
        seed_draws(self.admin, 1, start=321, seed=99)
        self.admin.execute("INSERT INTO job(kind, lottery_slug) VALUES ('analyze','lotofacil')")
        analisador.process_pending(self.conn, threading.Event())
        self.assertEqual(self.conn.execute("select count(*) from analysis_run where status='succeeded'").fetchone()[0], 8)
        self.assertEqual(self.conn.execute("select max(window_end_contest) from analysis_run where window_label='all'").fetchone()[0], 321)

    def test_only_validated_draws_are_analyzed_and_failure_is_recorded(self):
        import analisador
        import stats_jobs
        seed_draws(self.admin, 40)
        orig = stats_jobs.stats.analyze_window
        stats_jobs.stats.analyze_window = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("falha simulada"))
        try:
            self.admin.execute("INSERT INTO job(kind, lottery_slug) VALUES ('analyze','lotofacil')")
            analisador.process_pending(self.conn, threading.Event())
        finally:
            stats_jobs.stats.analyze_window = orig
        self.assertEqual(self.conn.execute("select status from job").fetchone()[0], "failed")
        self.assertEqual(self.conn.execute("select count(*) from analysis_run where status='failed'").fetchone()[0], 1)
        # retry: run falho é removido e recalculado
        self.admin.execute("INSERT INTO job(kind, lottery_slug) VALUES ('analyze','lotofacil')")
        analisador.process_pending(self.conn, threading.Event())
        self.assertEqual(self.conn.execute("select count(*) from analysis_run where status='failed'").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("select count(*) from analysis_run where status='succeeded'").fetchone()[0], 2)  # 30 e all


if __name__ == "__main__":
    unittest.main()
