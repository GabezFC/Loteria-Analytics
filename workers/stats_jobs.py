"""Jobs de análise: tabela de probabilidades exatas e estatísticas por janela (somente concursos validados).

Idempotência: uma análise é identificada por (modalidade, método, janela, hash de parâmetros, versão do
código, fingerprint dos dados da janela). Reexecutar sem novos dados não recalcula nada.
"""
from __future__ import annotations

import hashlib
import json
import zlib

import numpy as np
import psycopg
from psycopg.types.json import Jsonb

import probabilities as prob
import stats
from analisador import handler

METHOD = "statistics"
PARAMS = {"sims": 200, "perms": 300, "min_inference_n": stats.MIN_INFERENCE_N, "min_combo_n": stats.MIN_COMBO_N, "top_combos": stats.TOP_COMBOS}
PARAMS_HASH = hashlib.md5(json.dumps(PARAMS, sort_keys=True).encode()).hexdigest()
CODE_VERSION = f"{stats.STATS_VERSION}+np{np.__version__.split('.')[0]}"


def ensure_probability_table(conn: psycopg.Connection) -> int:
    """Popula/atualiza probability_table com as fórmulas exatas. Idempotente."""
    written = 0
    price_rows = conn.execute("SELECT slug, pool_size, draw_size, min_bet_size, max_bet_size, simple_price FROM lottery_type").fetchall()
    prizes = {"megasena": (6, 5, 4), "lotofacil": (15, 14, 13, 12, 11), "quina": (5, 4, 3, 2)}
    with conn.transaction():
        for slug, pool, draw, lo, hi, price in price_rows:
            for r in prob.tier_table(pool, draw, prizes[slug], lo, hi):
                denom = prob.combinations_total(pool, draw)
                # r.exact é Fraction sobre C(N,k): numerador inteiro = exact * denom
                exact_num = r.exact * denom
                atleast_num = r.at_least * denom
                assert exact_num.denominator == 1 and atleast_num.denominator == 1
                conn.execute(
                    "INSERT INTO probability_table(lottery_slug,bet_size,hits,is_prize_tier,exact_numerator,exact_denominator,at_least_numerator,probability,at_least_probability,simple_games,cost,formula_version) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (lottery_slug,bet_size,hits) DO UPDATE SET "
                    "is_prize_tier=EXCLUDED.is_prize_tier, exact_numerator=EXCLUDED.exact_numerator, exact_denominator=EXCLUDED.exact_denominator, at_least_numerator=EXCLUDED.at_least_numerator, "
                    "probability=EXCLUDED.probability, at_least_probability=EXCLUDED.at_least_probability, simple_games=EXCLUDED.simple_games, cost=EXCLUDED.cost, formula_version=EXCLUDED.formula_version",
                    (slug, r.bet_size, r.hits, r.is_prize_tier, int(exact_num), denom, int(atleast_num), float(r.exact), float(r.at_least), r.simple_games, price * r.simple_games, prob.FORMULA_VERSION),
                )
                written += 1
    return written


def load_draws(conn: psycopg.Connection, slug: str) -> tuple[np.ndarray, np.ndarray]:
    rows = conn.execute(
        "SELECT d.contest, array_agg(n.number ORDER BY n.number) FROM lottery_draw d JOIN draw_number n USING (draw_id) "
        "WHERE d.lottery_slug=%s GROUP BY d.contest ORDER BY d.contest", (slug,)
    ).fetchall()
    if not rows:
        return np.array([], dtype=np.int64), np.empty((0, 0), dtype=np.int16)
    return np.array([r[0] for r in rows], dtype=np.int64), np.array([r[1] for r in rows], dtype=np.int16)


def run_window(conn: psycopg.Connection, slug: str, pool: int, k: int, label: str, size: int | None, contests: np.ndarray, draws: np.ndarray, job_id: int | None) -> str:
    if size is not None:
        if len(contests) < size:
            return "skipped"
        contests, draws = contests[-size:], draws[-size:]
    fp = stats.fingerprint(contests, draws)
    seed = zlib.crc32(f"{slug}:{label}:{int(contests[-1])}:{fp}".encode()) & 0x7FFFFFFF
    existing = conn.execute(
        "SELECT analysis_run_id, status FROM analysis_run WHERE lottery_slug=%s AND method=%s AND window_label=%s AND params_hash=%s AND code_version=%s AND data_fingerprint=%s",
        (slug, METHOD, label, PARAMS_HASH, CODE_VERSION, fp),
    ).fetchone()
    if existing and existing[1] == "succeeded":
        return "cached"
    with conn.transaction():
        if existing:
            conn.execute("DELETE FROM analysis_run WHERE analysis_run_id=%s", (existing[0],))
        run_id = conn.execute(
            "INSERT INTO analysis_run(lottery_slug,method,window_label,window_size,window_start_contest,window_end_contest,sample_size,params,params_hash,code_version,seed,data_fingerprint,status,job_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'running',%s) RETURNING analysis_run_id",
            (slug, METHOD, label, size, int(contests[0]), int(contests[-1]), len(contests), Jsonb(PARAMS), PARAMS_HASH, CODE_VERSION, seed, fp, job_id),
        ).fetchone()[0]
    try:
        res = stats.analyze_window(contests, draws, pool, k, seed, sims=PARAMS["sims"], perms=PARAMS["perms"])
        with conn.transaction():
            for r in res["number_stats"]:
                conn.execute(
                    "INSERT INTO number_stat(analysis_run_id,number,frequency,relative_frequency,expected_frequency,z_score,ci_low,ci_high,current_delay,max_delay,mean_gap,metadata) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (run_id, r["number"], r["frequency"], r["relative_frequency"], r["expected_frequency"], r["z_score"], r["ci_low"], r["ci_high"], r["current_delay"], r["max_delay"], r["mean_gap"], Jsonb(r["metadata"])),
                )
            for c in res["combinations"]:
                conn.execute(
                    "INSERT INTO combination_stat(analysis_run_id,combo_size,numbers,observed,expected,lift,z_score,p_value,q_value,sample_size) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (run_id, c["combo_size"], c["numbers"], c["observed"], c["expected"], c["lift"], c["z_score"], c["p_value"], c["q_value"], c["sample_size"]),
                )
            for kind in ("distributions", "inference", "meta", "combination_meta"):
                if res.get(kind) is not None:
                    conn.execute("INSERT INTO analysis_result(analysis_run_id,kind,payload) VALUES (%s,%s,%s)", (run_id, kind, Jsonb(res[kind])))
            conn.execute("UPDATE analysis_run SET status='succeeded', completed_at=now() WHERE analysis_run_id=%s", (run_id,))
        return "computed"
    except Exception as exc:
        with conn.transaction():
            conn.execute("UPDATE analysis_run SET status='failed', completed_at=now(), error=%s WHERE analysis_run_id=%s", (f"{type(exc).__name__}: {exc}"[:1000], run_id))
        raise


@handler("analyze")
def analyze(conn: psycopg.Connection, job_id: int, slug: str | None, params: dict) -> None:
    ensure_probability_table(conn)
    slugs = [slug] if slug else [r[0] for r in conn.execute("SELECT slug FROM lottery_type ORDER BY slug").fetchall()]
    for s in slugs:
        pool, k = conn.execute("SELECT pool_size, draw_size FROM lottery_type WHERE slug=%s", (s,)).fetchone()
        contests, draws = load_draws(conn, s)
        if len(contests) == 0:
            print(f"analisador: {s} sem concursos validados", flush=True)
            continue
        outcomes = {}
        for label, size in stats.WINDOWS:
            outcomes[label] = run_window(conn, s, pool, k, label, size, contests, draws, job_id)
        print(f"analisador: job {job_id} {s}: n={len(contests)} janelas={outcomes}", flush=True)
