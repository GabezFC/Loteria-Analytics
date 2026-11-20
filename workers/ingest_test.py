"""Testes do coletor. Parser: offline. Integração: exige PGHOST (banco descartável) — use scripts/test-workers.sh."""
import io
import os
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from openpyxl import Workbook

from ingest import LOTTERIES, parse_money, parse_workbook

QUINA = LOTTERIES["quina"]
QH = ["Concurso", "Data Sorteio"] + [f"Bola{i}" for i in range(1, 6)]
QP = ["Ganhadores 5 acertos", "Rateio 5 acertos", "Ganhadores 4 acertos", "Rateio 4 acertos",
      "Ganhadores 3 acertos", "Rateio 3 acertos", "Ganhadores 2 acertos", "Rateio 2 acertos"]


def fixture(headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    wb.close()
    return out.getvalue()


def quina_row(contest, d, nums, prizes=(0, "R$0,00", 5, "R$1.000,50", 100, "R$50,00", 1000, "R$4,33")):
    return [contest, d, *nums, *prizes]


class ParserTests(unittest.TestCase):
    def test_normalizes_headers_sorts_balls_and_orders_contests(self):
        data = fixture(["Concurso", "Data do Sorteio", "Bola 1", "Bola 2", "Bola 3", "Bola 4", "Bola 5"],
                       [[2, datetime(2026, 1, 2), 22, 1, 80, 7, 9], [1, date(2026, 1, 1), 3, 5, 6, 8, 10]])
        draws = parse_workbook(data, QUINA).draws
        self.assertEqual([d.contest for d in draws], [1, 2])
        self.assertEqual(draws[1].numbers, (1, 7, 9, 22, 80))

    def test_invalid_rows_are_quarantined_not_imported(self):
        rows = [quina_row(1, "01/01/2026", [1, 2, 3, 4, 5]),
                quina_row(2, "02/01/2026", [1, 2, 3, 4, 4]),      # repetida
                quina_row(3, "03/01/2026", [1, 2, 3, 4, 81]),     # fora da faixa
                quina_row(4, "31/02/2026", [1, 2, 3, 4, 5]),      # data inválida
                quina_row(5, "05/01/2026", [1, 2, 3, 4, 6])]
        parsed = parse_workbook(fixture(QH + QP, rows), QUINA)
        self.assertEqual([d.contest for d in parsed.draws], [1, 5])
        self.assertEqual([r.contest for r in parsed.rejects], [2, 3, 4])
        self.assertTrue(all(r.kind == "draw" for r in parsed.rejects))

    def test_too_many_rejects_aborts(self):
        rows = [quina_row(i, "01/01/2026", [1, 1, 1, 1, 1]) for i in range(1, 12)]
        rows.append(quina_row(12, "01/01/2026", [1, 2, 3, 4, 5]))
        with self.assertRaisesRegex(ValueError, "formato da fonte suspeito"):
            parse_workbook(fixture(QH + QP, rows), QUINA)

    def test_missing_column_duplicate_contest_non_xlsx(self):
        with self.assertRaisesRegex(ValueError, "Cabeçalho"):
            parse_workbook(fixture(["Concurso", "Data do Sorteio", "Bola 1"], [[1, date(2026, 1, 1), 1]]), QUINA)
        dup = fixture(QH, [[1, date(2026, 1, 1), 1, 2, 3, 4, 5], [1, date(2026, 1, 2), 6, 7, 8, 9, 10]])
        with self.assertRaisesRegex(ValueError, "duplicado"):
            parse_workbook(dup, QUINA)
        with self.assertRaisesRegex(ValueError, "não é um XLSX"):
            parse_workbook(b"not an xlsx", QUINA)

    def test_prize_tiers_parsed_and_required(self):
        parsed = parse_workbook(fixture(QH + QP, [quina_row(1, "01/01/2026", [1, 2, 3, 4, 5])]), QUINA, require_prizes=True)
        self.assertEqual(parsed.draws[0].tiers, ((5, 0, Decimal("0.00")), (4, 5, Decimal("1000.50")), (3, 100, Decimal("50.00")), (2, 1000, Decimal("4.33"))))
        with self.assertRaisesRegex(ValueError, "premiação"):
            parse_workbook(fixture(QH, [[1, "01/01/2026", 1, 2, 3, 4, 5]]), QUINA, require_prizes=True)

    def test_invalid_prize_is_quarantined_but_draw_kept_without_tiers(self):
        row = quina_row(1, "01/01/2026", [1, 2, 3, 4, 5], (0, "abc", 5, "R$1,00", 1, "R$1,00", 1, "R$1,00"))
        parsed = parse_workbook(fixture(QH + QP, [row]), QUINA, require_prizes=True)
        self.assertEqual(len(parsed.draws), 1)
        self.assertIsNone(parsed.draws[0].tiers)
        self.assertEqual(parsed.rejects[0].kind, "prize")

    def test_money(self):
        self.assertEqual(parse_money("R$1.234.567,89"), Decimal("1234567.89"))
        self.assertEqual(parse_money("R$0,00"), Decimal("0.00"))
        self.assertIsNone(parse_money(None))
        with self.assertRaises(ValueError):
            parse_money("R$-1,00")


@unittest.skipUnless(os.environ.get("PGHOST") and os.environ.get("TEST_ADMIN_DSN"), "requer PGHOST e TEST_ADMIN_DSN de banco descartável")
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.conn = psycopg.connect(autocommit=True)
        # Limpeza com superusuário do banco descartável (o papel worker não tem DELETE por desenho).
        with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as admin:
            for t in ("analysis_run", "job", "ingest_quarantine", "ingest_divergence", "ingest_draw_change", "draw_extra",
                      "draw_prize_tier", "draw_number", "lottery_draw", "ingest_run", "collector_status"):
                admin.execute(f"DELETE FROM {t}")

    def tearDown(self):
        self.conn.close()

    def ingest(self, rows, headers=QH + QP):
        import ingest
        return ingest.ingest_one(QUINA, fixture(headers, rows), "fixture://quina", batch_size=2)

    def count(self, sql):
        return self.conn.execute(sql).fetchone()[0]

    def numbers_of(self, contest):
        return self.conn.execute("select array_agg(number order by number) from draw_number n join lottery_draw d using(draw_id) where contest=%s", (contest,)).fetchone()[0]

    def base_rows(self):
        return [quina_row(i, f"0{i}/01/2026", [i, i + 1, i + 2, i + 3, i + 4]) for i in range(1, 6)]

    def test_first_load_idempotent_and_enqueues_analysis(self):
        r1 = self.ingest(self.base_rows())
        self.assertEqual((r1["inserted"], r1["analysis_enqueued"]), (5, True))
        self.assertEqual(self.count("select count(*) from draw_prize_tier"), 20)
        self.assertEqual(self.count("select count(*) from job where kind='analyze' and status='pending'"), 1)
        r2 = self.ingest(self.base_rows())
        self.assertEqual((r2["inserted"], r2["unchanged"], r2["prize_changed"], r2["divergent"], r2["analysis_enqueued"]), (0, 5, 0, 0, False))
        self.assertEqual(self.count("select count(*) from lottery_draw"), 5)
        self.assertEqual(self.count("select count(*) from job"), 1)

    def test_incremental_adds_only_new_and_keeps_history(self):
        self.ingest(self.base_rows())
        r = self.ingest(self.base_rows() + [quina_row(6, "06/01/2026", [6, 7, 8, 9, 10])])
        self.assertEqual((r["inserted"], r["unchanged"]), (1, 5))
        self.assertEqual(self.count("select count(*) from lottery_draw"), 6)

    def test_divergence_preserves_validated_value_and_resolves(self):
        import ingest
        self.ingest(self.base_rows())
        rows = self.base_rows()
        rows[2] = quina_row(3, "03/01/2026", [10, 11, 12, 13, 14])
        self.assertEqual(self.ingest(rows)["divergent"], 1)
        self.assertEqual(self.count("select count(*) from lottery_draw"), 5)
        self.assertEqual(self.numbers_of(3), [3, 4, 5, 6, 7])  # valor validado preservado
        self.assertEqual(self.ingest(rows)["divergent"], 0)  # divergência aberta idêntica não duplica
        self.assertEqual(self.count("select count(*) from ingest_divergence where status='open'"), 1)
        ingest.resolve_divergence(self.count("select divergence_id from ingest_divergence"), "reject", "teste")
        self.assertEqual(self.count("select count(*) from ingest_divergence where status='rejected'"), 1)
        self.assertEqual(self.numbers_of(3), [3, 4, 5, 6, 7])

    def test_accept_divergence_updates_with_audit_trail(self):
        import ingest
        self.ingest(self.base_rows())
        rows = self.base_rows()
        rows[0] = quina_row(1, "01/01/2026", [20, 21, 22, 23, 24])
        self.ingest(rows)
        ingest.resolve_divergence(self.count("select divergence_id from ingest_divergence"), "accept")
        self.assertEqual(self.numbers_of(1), [20, 21, 22, 23, 24])
        self.assertEqual(self.count("select count(*) from ingest_draw_change where action='reconciled'"), 1)

    def test_prize_correction_is_audited(self):
        self.ingest(self.base_rows())
        rows = self.base_rows()
        rows[0] = quina_row(1, "01/01/2026", [1, 2, 3, 4, 5], (1, "R$9,00", 5, "R$1.000,50", 100, "R$50,00", 1000, "R$4,33"))
        self.assertEqual(self.ingest(rows)["prize_changed"], 1)
        self.assertEqual(self.count("select count(*) from ingest_draw_change where action='prize_reconciled'"), 1)

    def test_invalid_rows_quarantined_valid_rows_loaded(self):
        r = self.ingest(self.base_rows() + [quina_row(6, "06/01/2026", [1, 1, 2, 3, 4])])
        self.assertEqual((r["inserted"], r["quarantined"]), (5, 1))
        self.assertEqual(self.count("select count(*) from ingest_quarantine"), 1)
        self.assertEqual(self.count("select count(*) from lottery_draw where contest=6"), 0)

    def test_structural_failure_writes_nothing(self):
        import ingest
        with self.assertRaises(ValueError):
            ingest.ingest_one(QUINA, b"garbage", "fixture://bad")
        self.assertEqual(self.count("select count(*) from lottery_draw"), 0)
        self.assertEqual(self.count("select count(*) from ingest_run"), 0)

    def test_failure_mid_import_marks_run_failed_and_resumes(self):
        import ingest
        orig = ingest._apply_batch
        calls = {"n": 0}

        def boom(*a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("falha simulada")
            return orig(*a, **k)

        ingest._apply_batch = boom
        try:
            with self.assertRaises(RuntimeError):
                self.ingest(self.base_rows())
        finally:
            ingest._apply_batch = orig
        self.assertEqual(self.count("select count(*) from ingest_run where status='failed'"), 1)
        self.assertEqual(self.count("select count(*) from lottery_draw"), 2)  # lote 1 confirmado
        r = self.ingest(self.base_rows())  # retomada sem duplicar
        self.assertEqual((r["inserted"], r["unchanged"]), (3, 2))

    def test_concurrent_run_blocked_by_advisory_lock(self):
        import psycopg
        other = psycopg.connect(autocommit=True)
        try:
            other.execute("SELECT pg_advisory_lock(hashtextextended('cassino-ingest:quina', 0))")
            with self.assertRaisesRegex(RuntimeError, "concorrente"):
                self.ingest(self.base_rows())
        finally:
            other.close()

    def test_collector_records_failure_and_backoff(self):
        import coletor
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        nxt1 = coletor.record_attempt(self.conn, "quina", False, "HTTP 503", now)
        nxt2 = coletor.record_attempt(self.conn, "quina", False, "HTTP 503", now)
        self.assertLess(nxt1, nxt2)
        self.assertEqual(self.conn.execute("select consecutive_failures,last_error from collector_status where lottery_slug='quina'").fetchone(), (2, "HTTP 503"))
        coletor.record_attempt(self.conn, "quina", True, None, now)
        self.assertEqual(self.count("select consecutive_failures from collector_status where lottery_slug='quina'"), 0)

    def test_analyzer_consumes_job(self):
        import analisador
        import common
        import threading
        self.ingest(self.base_rows())
        self.assertEqual(analisador.process_pending(self.conn, threading.Event()), 1)
        self.assertEqual(self.count("select count(*) from job where status='succeeded'"), 1)
        self.assertIsNone(common.claim_job(self.conn, ["analyze"]))


if __name__ == "__main__":
    unittest.main()
