"""Jobs de experimento (backtest / Monte Carlo) e de sugestões. Registrado automaticamente pelo analisador."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import psycopg
from psycopg.types.json import Jsonb

import backtest as B
import probabilities as prob
import stats
import suggestions as S
from analisador import handler

PRIZE_HITS = {"megasena": (6, 5, 4), "lotofacil": (15, 14, 13, 12, 11), "quina": (5, 4, 3, 2)}
CODE_VERSION = f"{B.BACKTEST_VERSION}+{S.SUGGEST_VERSION}+np{np.__version__.split('.')[0]}"


def load_history(conn: psycopg.Connection, slug: str):
    from stats_jobs import load_draws
    contests, draws = load_draws(conn, slug)
    if len(contests) == 0:
        raise ValueError("sem concursos validados")
    return contests, draws


def load_payouts(conn: psycopg.Connection, slug: str, contests: np.ndarray, k: int) -> np.ndarray:
    """Matriz (n, k+1): rateio histórico por nº de acertos; 0 quando a faixa não teve ganhador (rateio desconhecido)."""
    idx = {int(c): i for i, c in enumerate(contests)}
    pay = np.zeros((len(contests), k + 1))
    for contest, hits, winners, amount in conn.execute(
        "SELECT d.contest, t.hits, t.winners, t.payout_amount FROM draw_prize_tier t JOIN lottery_draw d USING (draw_id) WHERE d.lottery_slug=%s", (slug,)
    ):
        if winners and winners > 0 and amount is not None and contest in idx and hits <= k:
            pay[idx[contest], hits] = float(amount)
    return pay


def _update_progress(conn: psycopg.Connection, exp_id: int, done: int, total: int, stage: str) -> None:
    conn.execute("UPDATE experiment SET progress=%s WHERE experiment_id=%s", (Jsonb({"done": done, "total": total, "stage": stage}), exp_id))


def _store_results(conn: psycopg.Connection, exp_id: int, results: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM experiment_result WHERE experiment_id=%s", (exp_id,))
    for r in results:
        conn.execute(
            "INSERT INTO experiment_result(experiment_id,model_name,metric_name,value,ci_low,ci_high,baseline_value,baseline_ci_low,baseline_ci_high,p_value,q_value,verdict,payload) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (exp_id, r["model_name"], r["metric_name"], r.get("value"), r.get("ci_low"), r.get("ci_high"), r.get("baseline_value"), r.get("baseline_ci_low"),
             r.get("baseline_ci_high"), r.get("p_value"), r.get("q_value"), r.get("verdict"), Jsonb(r.get("payload", {}))),
        )


@handler("experiment")
def run_experiment(conn: psycopg.Connection, job_id: int, slug: str | None, params: dict) -> None:
    exp_id = int(params["experiment_id"])
    row = conn.execute("SELECT kind, lottery_slug, config, seed FROM experiment WHERE experiment_id=%s", (exp_id,)).fetchone()
    if row is None:
        raise ValueError(f"experimento {exp_id} inexistente")
    kind, lottery, cfg, seed = row
    conn.execute("UPDATE experiment SET status='running', started_at=now(), error=NULL, progress=NULL WHERE experiment_id=%s", (exp_id,))
    try:
        pool, k, price = conn.execute("SELECT pool_size, draw_size, simple_price FROM lottery_type WHERE slug=%s", (lottery,)).fetchone()
        price = float(price)
        contests, draws = load_history(conn, lottery)
        fp = stats.fingerprint(contests, draws)
        if kind == "backtest":
            models = cfg.get("models") or [m for m, v in B.MODEL_CATALOG.items() if v["default"]]
            payouts = load_payouts(conn, lottery, contests, k)
            out = B.run_backtest(
                draws, contests, pool, k, price, PRIZE_HITS[lottery], payouts, models, int(cfg.get("test_contests", 500)), int(cfg.get("tickets_per_contest", 10)),
                int(cfg.get("seeds", 5)), int(cfg.get("baseline_replicates", 500)), int(cfg.get("refit_every", 50)), int(seed),
                progress=lambda d, t, s: _update_progress(conn, exp_id, d, t, s),
            )
            m = out["meta"]
            with conn.transaction():
                _store_results(conn, exp_id, out["results"])
                conn.execute(
                    "UPDATE experiment SET status='succeeded', completed_at=now(), models=%s, train_cutoff_contest=%s, test_start_contest=%s, test_end_contest=%s, n_hypotheses=%s, "
                    "code_version=%s, data_fingerprint=%s, conclusion=%s, progress=%s WHERE experiment_id=%s",
                    (models, m["train_cutoff_contest"], m["test_start_contest"], m["test_end_contest"], m["n_hypotheses"], CODE_VERSION, fp,
                     Jsonb({**out["conclusion"], "data_used": m["data_used"], "model_info": m["model_info"], "expected_false_positives_at_05": m["expected_false_positives_at_05"]}),
                     Jsonb({"done": 1, "total": 1, "stage": "concluído"}), exp_id),
                )
        elif kind == "montecarlo":
            import simulate
            payouts = load_payouts(conn, lottery, contests, k)
            recent = payouts[-1000:]
            tier_payouts = {h: float(np.median(recent[recent[:, h] > 0, h])) for h in PRIZE_HITS[lottery][1:] if (recent[:, h] > 0).any()}
            conn.execute("UPDATE experiment SET progress=%s WHERE experiment_id=%s", (Jsonb({"done": 0, "total": 1, "stage": "simulando"}), exp_id))
            res = simulate.run_montecarlo(pool, k, int(cfg["tickets_per_contest"]), int(cfg["contests"]), int(cfg["replicates"]), int(seed), price, tier_payouts, PRIZE_HITS[lottery])
            limits = res["limitations"] + [f"Prêmios por faixa = mediana histórica (últimos 1000 concursos) dos rateios: {tier_payouts}."]
            rows = [
                {"model_name": "montecarlo", "metric_name": "hits_distribution", "p_value": res["hits_distribution"]["gof_p_value"], "payload": res["hits_distribution"]},
                {"model_name": "montecarlo", "metric_name": "net_result_paths", "payload": res["net_result_paths"]},
                {"model_name": "montecarlo", "metric_name": "final_net_distribution", "value": res["final_net_distribution"]["mean"], "payload": res["final_net_distribution"]},
                {"model_name": "montecarlo", "metric_name": "jackpot_probability", "value": res["jackpot_probability"]["value"], "payload": res["jackpot_probability"]},
            ]
            fnd = res["final_net_distribution"]
            summary = (f"Simulação de {res['meta']['replicates']} réplicas de {res['meta']['contests']} concursos com {res['meta']['tickets_per_contest']} bilhetes/concurso (custo total "
                       f"R$ {res['total_cost']:.2f}): resultado líquido médio R$ {fnd['mean']:.2f}; {fnd['share_positive'] * 100:.1f}% das réplicas terminam no positivo; "
                       f"{fnd['share_total_loss'] * 100:.1f}% sem nenhum prêmio. Chance exata de ao menos um prêmio principal no período: {res['jackpot_probability']['value']:.3e}.")
            with conn.transaction():
                _store_results(conn, exp_id, rows)
                conn.execute(
                    "UPDATE experiment SET status='succeeded', completed_at=now(), models=%s, n_hypotheses=0, code_version=%s, data_fingerprint=%s, conclusion=%s, progress=%s WHERE experiment_id=%s",
                    (["montecarlo"], f"{res['meta']['version']}+np{np.__version__.split('.')[0]}", fp,
                     Jsonb({"verdict": "inconclusive", "summary": summary + " A simulação mostra a variabilidade esperada ao acaso; não prevê resultados nem recomenda gastos.", "limitations": limits}),
                     Jsonb({"done": 1, "total": 1, "stage": "concluído"}), exp_id),
                )
        else:
            raise ValueError(f"tipo de experimento desconhecido: {kind}")
        print(f"analisador: experimento {exp_id} ({kind} {lottery}) concluído", flush=True)
    except Exception as exc:
        conn.execute("UPDATE experiment SET status='failed', completed_at=now(), error=%s WHERE experiment_id=%s", (f"{type(exc).__name__}: {exc}"[:1000], exp_id))
        raise


@handler("suggestion")
def run_suggestion(conn: psycopg.Connection, job_id: int, slug: str | None, params: dict) -> None:
    set_id = int(params["set_id"])
    row = conn.execute("SELECT lottery_slug, strategy, seed, budget, ticket_count FROM suggestion_set WHERE set_id=%s", (set_id,)).fetchone()
    if row is None:
        raise ValueError(f"conjunto {set_id} inexistente")
    lottery, strategy, seed, budget, count = row
    conn.execute("UPDATE suggestion_set SET status='running', error=NULL WHERE set_id=%s", (set_id,))
    try:
        pool, k, price = conn.execute("SELECT pool_size, draw_size, simple_price FROM lottery_type WHERE slug=%s", (lottery,)).fetchone()
        price = float(price)
        contests, draws = load_history(conn, lottery)
        hist = B.History.build(draws, pool, k) if strategy in S.STRATEGY_MODEL else None
        tickets = S.generate(strategy, hist, pool, k, int(count), int(seed))
        total = prob.combinations_total(pool, k)
        model = S.STRATEGY_MODEL.get(strategy)
        evidence = None
        if model:
            ev = conn.execute(
                "SELECT e.experiment_id, r.verdict FROM experiment e JOIN experiment_result r USING (experiment_id) WHERE e.lottery_slug=%s AND e.kind='backtest' AND e.status='succeeded' "
                "AND r.model_name=%s AND r.metric_name='mean_hits_per_ticket' ORDER BY e.experiment_id DESC LIMIT 1", (lottery, model)).fetchone()
            if ev:
                evidence = {"experiment_id": int(ev[0]), "model_name": model, "verdict": ev[1]}
        explanation = {
            "strategy": strategy, "version": S.SUGGEST_VERSION, "seed": int(seed), "based_on_contest": int(contests[-1]),
            "text": {
                "uniform_random": "Bilhetes uniformes distintos. É o baseline: nenhum método abaixo é comprovadamente melhor.",
                "diversity": "Bilhetes escolhidos para repetir o mínimo de dezenas entre si (menos redundância). Não altera a chance de cada bilhete.",
                "frequency_weighted": "Sorteio ponderado pela frequência suavizada dos últimos 100 concursos. Em sorteios justos isso não aumenta a chance de acerto.",
                "delay_weighted": "Sorteio ponderado pelo atraso de cada dezena (falácia do jogador). Em sorteios justos isso não aumenta a chance de acerto.",
            }[strategy],
            "evidence_note": "Sem experimento de backtest concluído para este método." if (model and not evidence) else None,
        }
        with conn.transaction():
            conn.execute("DELETE FROM suggestion WHERE set_id=%s", (set_id,))
            for i, (nums, score) in enumerate(tickets, start=1):
                conn.execute(
                    "INSERT INTO suggestion(set_id,position,numbers,heuristic_score,score_interpretation,jackpot_numerator,jackpot_denominator,cost) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (set_id, i, nums, score, S.INTERPRETATION[strategy], 1, total, price))
            conn.execute(
                "UPDATE suggestion_set SET status='succeeded', completed_at=now(), based_on_contest=%s, explanation=%s, evidence=%s, total_cost=%s WHERE set_id=%s",
                (int(contests[-1]), Jsonb(explanation), Jsonb(evidence) if evidence else None, round(price * len(tickets), 2), set_id))
        print(f"analisador: sugestões {set_id} ({strategy} {lottery}, {len(tickets)} bilhetes) geradas", flush=True)
    except Exception as exc:
        conn.execute("UPDATE suggestion_set SET status='failed', completed_at=now(), error=%s WHERE set_id=%s", (f"{type(exc).__name__}: {exc}"[:1000], set_id))
        raise
