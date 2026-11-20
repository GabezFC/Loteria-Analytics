"""Simulação Monte Carlo de bilhetes simples aleatórios (variabilidade de custo/retorno). NÃO prevê resultados.

Modelo: sorteio uniforme de k entre N; cada bilhete simples de k dezenas faz X ~ Hipergeométrica(N, k, k) acertos.
Num mesmo concurso, os m bilhetes são tratados como independentes (multinomial sobre a pmf exata): aproximação válida
porque m ≪ C(N,k) (a correlação induzida pelo sorteio comum é desprezível; ver limitações). O histórico não entra.
"""
from __future__ import annotations

import math
from fractions import Fraction
from math import comb
from typing import Any

import numpy as np
from scipy import stats as sps

import probabilities as prob
from stats import _merge_small_bins, clean

SIM_VERSION = "montecarlo-v1"
PCTS = (5, 25, 50, 75, 95)
EXACT_FRACTION_MAX_CONTESTS = 20


def _validate(pool: int, draw: int, m: int, contests: int, replicates: int, price: float, tier_payouts: dict[int, float], max_cells: int) -> None:
    if not (1 <= draw <= pool):
        raise ValueError("requer 1 <= k <= N")
    if m < 1:
        raise ValueError("tickets_per_contest deve ser >= 1")
    if not (1 <= contests <= 5000):
        raise ValueError("contests deve estar entre 1 e 5000")
    if not (10 <= replicates <= 2000):
        raise ValueError("replicates deve estar entre 10 e 2000")
    if m > comb(pool, draw):
        raise ValueError("tickets_per_contest excede o número de combinações distintas C(N,k)")
    if replicates * contests * (draw + 1) > max_cells:
        raise ValueError(f"simulação excede o limite de {max_cells} células (réplicas × concursos × (k+1)); reduza o tamanho")
    if price < 0 or any(v < 0 for v in tier_payouts.values()):
        raise ValueError("preço e prêmios devem ser >= 0")
    if any(not (0 <= h <= draw) for h in tier_payouts):
        raise ValueError("faixas de prêmio devem estar entre 0 e k acertos")


def run_montecarlo(
    pool: int, draw: int, tickets_per_contest: int, contests: int, replicates: int, seed: int,
    simple_price: float, tier_payouts: dict[int, float], prize_hits: tuple[int, ...],
    max_cells: int = 40_000_000, checkpoints: int = 50,
) -> dict[str, Any]:
    m = tickets_per_contest
    _validate(pool, draw, m, contests, replicates, simple_price, tier_payouts, max_cells)
    rng = np.random.default_rng(seed)
    pmf = np.array([float(prob.hits_probability(pool, draw, draw, r)) for r in range(draw + 1)])
    pmf = pmf / pmf.sum()
    jackpot = max(prize_hits)
    pay = np.zeros(draw + 1)
    for h in prize_hits:
        if h != jackpot:
            pay[h] = float(tier_payouts.get(h, 0.0))          # prêmio principal fica 0 (desconhecido/acumulável)
    cost_per_contest = m * simple_price
    cp_idx = np.unique(np.linspace(1, contests, min(checkpoints, contests)).round().astype(int))
    cum = {i: np.empty(replicates) for i in cp_idx}
    final = np.empty(replicates)
    obs = np.zeros(draw + 1)
    chunk = max(1, min(replicates, 20_000_000 // (contests * (draw + 1))))
    start = 0
    wanted = [int(i) for i in cp_idx]
    ret_cp = np.empty((replicates, len(wanted)))
    while start < replicates:
        c = min(chunk, replicates - start)
        counts = rng.multinomial(m, pmf, size=(c, contests))          # (c, contests, draw+1)
        obs += counts.sum(axis=(0, 1))
        per_contest = counts @ pay                                    # prêmio por concurso
        cumret = np.cumsum(per_contest, axis=1)
        ret_cp[start:start + c] = cumret[:, [i - 1 for i in wanted]]
        final[start:start + c] = cumret[:, -1] - cost_per_contest * contests
        start += c
    nets = ret_cp - cost_per_contest * np.array(wanted)[None, :]
    percentiles = {str(p): np.percentile(nets, p, axis=0).tolist() for p in PCTS}
    total_tickets = int(replicates * contests * m)
    expected = pmf * total_tickets
    o, e = _merge_small_bins(obs, expected)
    p_gof = None
    if len(e) >= 2:
        chi2 = float(((o - e) ** 2 / e).sum())
        p_gof = float(sps.chi2.sf(chi2, len(e) - 1))
    edges = np.histogram_bin_edges(final, bins=20)
    counts_h, edges = np.histogram(final, bins=edges)
    per_contest_prob = Fraction(m, comb(pool, draw))
    if contests <= EXACT_FRACTION_MAX_CONTESTS:
        period = 1 - (1 - per_contest_prob) ** contests
        period_value, num, den = float(period), str(period.numerator), str(period.denominator)
    else:  # fração exata cresce com contests × dígitos: usa forma estável em ponto flutuante
        period_value, num, den = -math.expm1(contests * math.log1p(-float(per_contest_prob))), None, None
    res = {
        "hits_distribution": {"values": list(range(draw + 1)), "observed_share": (obs / total_tickets).tolist(), "expected_share": pmf.tolist(),
                              "gof_p_value": p_gof, "tickets_total": total_tickets},
        "net_result_paths": {"checkpoints": wanted, "percentiles": percentiles, "cost_curve": [cost_per_contest * i for i in wanted]},
        "final_net_distribution": {"edges": edges.tolist(), "counts": counts_h.tolist(), "mean": float(final.mean()), "median": float(np.median(final)),
                                   "share_positive": float((final > 0).mean()), "share_total_loss": float((final == -cost_per_contest * contests).mean())},
        "jackpot_probability": {"value": period_value, "numerator": num, "denominator": den,
                                "event": "pelo menos um prêmio principal no período (bilhetes simples distintos por concurso)"},
        "total_cost": float(cost_per_contest * contests),
        "limitations": [
            "O prêmio principal é contado como R$ 0 no retorno (valor desconhecido e acumulável); o retorno simulado é, portanto, um piso.",
            "Prêmios por faixa usam valores nominais históricos (mediana), sem impostos e sem considerar que o rateio mudaria com mais ganhadores.",
            "Bilhetes do mesmo concurso são tratados como independentes (multinomial); a aproximação é desprezível quando m ≪ C(N,k).",
            "A simulação mostra a variabilidade esperada ao acaso; não prevê resultados nem recomenda aumentar gastos. O valor esperado de loterias é negativo.",
        ],
        "meta": {"version": SIM_VERSION, "seed": seed, "replicates": replicates, "contests": contests, "tickets_per_contest": m},
    }
    return clean(res)
