"""Geração de bilhetes experimentais (sugestões ilustrativas). NÃO há previsão: todo bilhete simples tem a mesma chance exata 1/C(N,k).

Estratégias:
- uniform_random      : bilhetes uniformes distintos (referência).
- diversity           : cobre o volante com pouca sobreposição entre bilhetes (só afeta redundância, não a chance individual).
- frequency_weighted  : sorteio proporcional à frequência suavizada recente (modelo `freq_w100` do backtest).
- delay_weighted      : sorteio proporcional ao atraso atual (modelo `delay_overdue` do backtest).

`heuristic_score` ∈ [0,1] é uma pontuação DESCRITIVA da estratégia (diversidade ou ranking médio das dezenas); jamais é probabilidade.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

import backtest as B

SUGGEST_VERSION = "suggest-v1"
STRATEGIES = ("uniform_random", "diversity", "frequency_weighted", "delay_weighted")
STRATEGY_MODEL = {"frequency_weighted": "freq_w100", "delay_weighted": "delay_overdue"}
INTERPRETATION = {
    "uniform_random": "Pontuação neutra (0,5): sorteio uniforme, todos os bilhetes são equivalentes. Não é probabilidade.",
    "diversity": "Pontuação descritiva de diversidade (1 = nenhuma dezena repetida de outros bilhetes do conjunto). Não é probabilidade de acerto.",
    "frequency_weighted": "Pontuação descritiva: posição média (0–1) das dezenas no ranking de frequência recente. Não é probabilidade de acerto.",
    "delay_weighted": "Pontuação descritiva: posição média (0–1) das dezenas no ranking de atraso. Não é probabilidade de acerto.",
}
MAX_ATTEMPTS = 2000


def _rank01(x: np.ndarray) -> np.ndarray:
    return np.argsort(np.argsort(x)) / max(len(x) - 1, 1)


def generate(strategy: str, history: "B.History | None", pool: int, k: int, tickets: int, seed: int) -> list[tuple[list[int], float]]:
    if strategy not in STRATEGIES:
        raise ValueError(f"estratégia desconhecida: {strategy}")
    if not (1 <= tickets <= 200):
        raise ValueError("tickets deve estar entre 1 e 200")
    if tickets > math.comb(pool, k):
        raise ValueError("mais bilhetes que combinações possíveis")
    rng = np.random.default_rng(seed)
    n = 0 if history is None else history.M.shape[0]
    if strategy in STRATEGY_MODEL:
        if history is None or n < B.MIN_HISTORY:
            raise ValueError("histórico insuficiente para esta estratégia")
        w = B.shrunk_freq(history, n, 100, B.SHRINK_WINDOW) if strategy == "frequency_weighted" else B.delay_weights(history, n)
        rank = _rank01(w)
    else:
        w, rank = np.ones(pool), None

    def draw_one(weights: np.ndarray) -> tuple[int, ...]:
        keys = np.log(weights) + rng.gumbel(size=pool)
        return tuple(sorted((np.argpartition(-keys, k - 1)[:k] + 1).tolist()))

    chosen: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()
    for _ in range(tickets):
        for attempt in range(MAX_ATTEMPTS):
            if strategy == "diversity" and chosen:
                cands = {draw_one(w) for _ in range(120)} - seen
                if not cands:
                    continue
                t = min(cands, key=lambda c: (max(len(set(c) & set(o)) for o in chosen), c))
            else:
                t = draw_one(w)
            if t not in seen:
                break
        else:
            raise RuntimeError("não foi possível gerar bilhetes distintos")
        seen.add(t)
        chosen.append(t)

    out: list[tuple[list[int], float]] = []
    for i, t in enumerate(chosen):
        if strategy == "uniform_random":
            score = 0.5
        elif strategy == "diversity":
            score = 1.0 if i == 0 else 1.0 - max(len(set(t) & set(o)) for o in chosen[:i]) / k
        else:
            score = float(np.mean([rank[x - 1] for x in t]))
        out.append((list(t), float(min(1.0, max(0.0, score)))))
    return out
