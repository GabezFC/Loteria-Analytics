"""Backtest walk-forward cronológico, modelos experimentais e comparação com baseline uniforme de mesmo custo.

Princípios:
- Em cada concurso de teste t, TODO modelo só enxerga os concursos < t (a função recebe `M[:t]`/`C[t]`; ver
  testes de vazamento por perturbação do futuro). Modelos supervisionados são reajustados a cada `refit_every`
  concursos usando apenas rótulos já conhecidos (< ponto de reajuste) e ficam congelados até o próximo.
- Sorteios justos são independentes e uniformes: espera-se NÃO encontrar vantagem. Os resultados negativos e
  inconclusivos são persistidos com o mesmo destaque. Scores de modelos não probabilísticos nunca são tratados
  como probabilidade.
- Baseline: bilhetes uniformes aleatórios com o MESMO número de bilhetes, custo, concursos e nº de sementes; a
  distribuição nula de cada métrica vem de `baseline_replicates` réplicas. p-values unilaterais (melhor que o baseline),
  corrigidos por Benjamini–Hochberg sobre TODAS as hipóteses testadas (modelos × métricas).
- "Replicado" = efeito significativo (q<0,05) no período inteiro E p<0,05 em cada metade cronológica do teste.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from scipy import stats as sps

from stats import benjamini_hochberg, clean

BACKTEST_VERSION = "backtest-v1"
MAX_TICKET_ROWS = 25_000          # test_contests * tickets_per_contest
MIN_HISTORY = 120                 # concursos mínimos antes do 1º teste
SHRINK_ALL, SHRINK_WINDOW = 200.0, 100.0
RIDGE = 5.0
LOGIT_MAX_TRAIN = 2000
ALPHA = 0.05

MODEL_CATALOG: dict[str, dict[str, Any]] = {
    "freq_all": dict(label="Frequência histórica suavizada", family="frequency", probabilistic=True, experimental=False, default=True,
                     description="p(i) = (f_i + a·k/N)/(n + a) usando todo o passado; encolhimento para a uniforme."),
    "freq_w100": dict(label="Frequência — últimos 100 concursos", family="frequency", probabilistic=True, experimental=False, default=True,
                      description="Mesma suavização, janela móvel de 100 concursos anteriores."),
    "freq_w30": dict(label="Frequência — últimos 30 concursos", family="frequency", probabilistic=True, experimental=False, default=False,
                     description="Janela móvel de 30 concursos (alta variância)."),
    "delay_overdue": dict(label="Atraso (dezenas 'devidas')", family="delay", probabilistic=False, experimental=True, default=True,
                          description="Peso crescente com o atraso atual (falácia do jogador): incluída para testar empiricamente; score, não probabilidade."),
    "ridge_logit": dict(label="Regressão logística regularizada (ML)", family="ml", probabilistic=True, experimental=True, default=True,
                        description="Logística ridge sobre frequências em janelas 10/30/100, atraso e repetição; reajustada a cada R concursos só com passado."),
}
BASELINE = "uniform_baseline"
METRICS = ("log_loss", "brier", "mean_hits_per_ticket", "tier_hit_rate", "return_ratio")
LOWER_IS_BETTER = {"log_loss", "brier"}


# ---------------------------------------------------------------- features e modelos
@dataclass
class History:
    """Pré-computação causal: C[t] = contagens dos concursos < t; D[t] = atrasos usando só concursos < t."""
    M: np.ndarray   # (n,N) bool
    C: np.ndarray   # (n+1,N) int32
    D: np.ndarray   # (n+1,N) int32 atraso (concursos desde a última aparição) ANTES do concurso t; D[n] = próximo concurso
    pool: int
    k: int

    @classmethod
    def build(cls, draws: np.ndarray, pool: int, k: int) -> "History":
        n = draws.shape[0]
        M = np.zeros((n, pool), dtype=bool)
        np.put_along_axis(M, draws - 1, True, axis=1)
        C = np.zeros((n + 1, pool), dtype=np.int32)
        np.cumsum(M, axis=0, out=C[1:])
        D = np.empty((n + 1, pool), dtype=np.int32)
        last = np.full(pool, -1, dtype=np.int64)
        for t in range(n):
            D[t] = t - 1 - last          # nunca visto => t (último = -1)
            last = np.where(M[t], t, last)
        D[n] = n - 1 - last
        return cls(M, C, D, pool, k)

    def freq(self, t: int, w: int | None) -> tuple[np.ndarray, int]:
        lo = 0 if w is None else max(0, t - w)
        return (self.C[t] - self.C[lo]).astype(float), t - lo

    def features(self, t: int) -> np.ndarray:
        """(N, 6) usando apenas concursos < t."""
        q = self.k / self.pool
        cols = []
        for w in (10, 30, 100):
            cnt, nw = self.freq(t, w)
            cols.append((cnt / max(nw, 1) - q) / math.sqrt(q * (1 - q) / max(nw, 1)))
        cols.append(np.log1p(self.D[t] * q))
        cols.append(self.M[t - 1].astype(float) if t > 0 else np.zeros(self.pool))
        cols.append(np.log1p(self.D[t] * q) ** 2)
        return np.stack(cols, axis=1)


def shrunk_freq(h: History, t: int, w: int | None, a: float) -> np.ndarray:
    cnt, nw = h.freq(t, w)
    q = h.k / h.pool
    return (cnt + a * q) / (nw + a)


def delay_weights(h: History, t: int) -> np.ndarray:
    return 1.0 + h.D[t] * (h.k / h.pool)


class RidgeLogit:
    """Regressão logística L2 (Newton/IRLS) com features padronizadas pelo conjunto de treino."""

    def __init__(self, ridge: float = RIDGE) -> None:
        self.ridge, self.mu, self.sd, self.w = ridge, None, None, None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "RidgeLogit":
        self.mu, self.sd = X.mean(axis=0), X.std(axis=0) + 1e-9
        Z = np.hstack([(X - self.mu) / self.sd, np.ones((len(X), 1))])
        w = np.zeros(Z.shape[1])
        w[-1] = math.log(y.mean() / (1 - y.mean()))
        reg = np.eye(Z.shape[1]) * self.ridge
        reg[-1, -1] = 0.0
        for _ in range(25):
            p = 1 / (1 + np.exp(-(Z @ w)))
            g = Z.T @ (p - y) + reg @ w
            H = (Z * (p * (1 - p))[:, None]).T @ Z + reg
            step = np.linalg.solve(H, g)
            w -= step
            if np.abs(step).max() < 1e-7:
                break
        self.w = w
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        Z = np.hstack([(X - self.mu) / self.sd, np.ones((len(X), 1))])
        return 1 / (1 + np.exp(-(Z @ self.w)))


def fit_ridge(h: History, r: int) -> RidgeLogit:
    """Treina só com rótulos de concursos < r (e features causais de cada t')."""
    lo = max(MIN_HISTORY - 20, r - LOGIT_MAX_TRAIN)
    ts = range(lo, r)
    X = np.vstack([h.features(t) for t in ts])
    y = np.concatenate([h.M[t].astype(float) for t in ts])
    return RidgeLogit().fit(X, y)


def normalize_probs(p: np.ndarray, k: int) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    for _ in range(5):
        p = np.clip(p * (k / p.sum()), 1e-6, 1 - 1e-6)
    return p


def predict_matrix(h: History, model: str, tests: np.ndarray, refit_every: int) -> tuple[np.ndarray, dict[str, Any]]:
    """Pesos/probabilidades (len(tests), N) para cada t em `tests` usando só o passado de t. Devolve também metadados."""
    q = h.k / h.pool
    out = np.empty((len(tests), h.pool))
    info: dict[str, Any] = {}
    if model == "ridge_logit":
        reg, fit_at, refits = None, None, 0
        for i, t in enumerate(tests):
            if reg is None or t - fit_at >= refit_every:
                reg, fit_at, refits = fit_ridge(h, int(t)), int(t), refits + 1
            out[i] = normalize_probs(reg.predict(h.features(int(t))), h.k)
        names = ["freq10", "freq30", "freq100", "log_delay", "prev_draw", "log_delay_sq", "intercept"]
        info = {"refits": refits, "last_fit_before_contest_index": fit_at, "standardized_coefficients": dict(zip(names, reg.w.tolist())),
                "ridge": RIDGE, "interpretation": "coeficientes próximos de 0 = sem sinal aprendível"}
        return out, info
    for i, t in enumerate(tests):
        t = int(t)
        if model == "freq_all":
            out[i] = shrunk_freq(h, t, None, SHRINK_ALL)
        elif model == "freq_w100":
            out[i] = shrunk_freq(h, t, 100, SHRINK_WINDOW)
        elif model == "freq_w30":
            out[i] = shrunk_freq(h, t, 30, SHRINK_WINDOW)
        elif model == "delay_overdue":
            out[i] = delay_weights(h, t)
        elif model == BASELINE:
            out[i] = q
        else:
            raise ValueError(f"modelo desconhecido: {model}")
    return out, info


# ---------------------------------------------------------------- bilhetes e métricas
def sample_tickets(weights: np.ndarray, tickets: int, k: int, rng: np.random.Generator) -> np.ndarray:
    """Amostragem sem reposição proporcional a `weights` (Gumbel-top-k / Plackett–Luce). weights: (T,N) -> (T,tickets,k) índices 0-based."""
    T, N = weights.shape
    logw = np.log(np.broadcast_to(weights[:, None, :], (T, tickets, N)))
    keys = logw + rng.gumbel(size=(T, tickets, N)).astype(np.float32)
    return np.argpartition(-keys, k - 1, axis=2)[:, :, :k]


def run_metrics(tick: np.ndarray, Y: np.ndarray, payout: np.ndarray, prize_mask: np.ndarray, price: float) -> dict[str, np.ndarray]:
    """Métricas por concurso (T,) para um conjunto de bilhetes (T,m,k)."""
    T, m, _ = tick.shape
    hits = Y[np.arange(T)[:, None, None], tick].sum(axis=2)  # (T,m)
    paid = np.take_along_axis(payout, hits, axis=1)           # (T,m)
    return {
        "mean_hits_per_ticket": hits.mean(axis=1),
        "tier_hit_rate": prize_mask[hits].mean(axis=1),
        "return_ratio": paid.sum(axis=1) / (m * price),
        "_hits": np.bincount(hits.ravel(), minlength=payout.shape[1]),
    }


def prob_losses(p: np.ndarray, Y: np.ndarray) -> dict[str, np.ndarray]:
    yf = Y.astype(float)
    ll = -(yf * np.log(p) + (1 - yf) * np.log1p(-p)).mean(axis=1)
    br = ((yf - p) ** 2).mean(axis=1)
    return {"log_loss": ll, "brier": br}


def _se(x: np.ndarray) -> float:
    return float(x.std(ddof=1) / math.sqrt(len(x))) if len(x) > 1 else float("nan")


def verdict_for(value: float, base_lo: float, base_hi: float, p: float, q: float, p_halves: tuple[float, float], higher_is_better: bool) -> str:
    better = value > base_hi if higher_is_better else value < base_lo
    worse = value < base_lo if higher_is_better else value > base_hi
    if better:
        if q < ALPHA and all(ph < ALPHA for ph in p_halves):
            return "better_replicated"
        if q < ALPHA:
            return "better_significant_not_replicated"
        return "better_not_significant"
    if worse:
        return "worse_than_baseline"
    return "indistinguishable"


# ---------------------------------------------------------------- orquestração
def run_backtest(
    draws: np.ndarray, contests: np.ndarray, pool: int, k: int, simple_price: float, prize_hits: tuple[int, ...], payouts: np.ndarray,
    models: list[str], test_contests: int, tickets: int, seeds: int, baseline_replicates: int, refit_every: int, seed: int,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    n = draws.shape[0]
    if not (1 <= tickets <= 50 and 1 <= seeds <= 10 and 50 <= baseline_replicates <= 2000 and 10 <= refit_every <= 500):
        raise ValueError("parâmetros fora dos limites (tickets 1–50, seeds 1–10, baseline_replicates 50–2000, refit_every 10–500)")
    if not (50 <= test_contests <= 2000):
        raise ValueError("test_contests deve estar entre 50 e 2000")
    if test_contests * tickets > MAX_TICKET_ROWS:
        raise ValueError(f"test_contests × tickets_per_contest excede {MAX_TICKET_ROWS} (limite de CPU/memória)")
    if n - test_contests < MIN_HISTORY:
        raise ValueError(f"histórico insuficiente: requer ao menos {MIN_HISTORY} concursos antes do período de teste")
    unknown = [m for m in models if m not in MODEL_CATALOG]
    if unknown or not models:
        raise ValueError(f"modelos inválidos: {unknown or 'nenhum informado'}")

    h = History.build(draws, pool, k)
    tests = np.arange(n - test_contests, n)
    Y = h.M[tests]
    pay = payouts[tests]
    prize_mask = np.zeros(k + 1, dtype=bool)
    prize_mask[list(prize_hits)] = True
    half = test_contests // 2
    ss = np.random.SeedSequence(seed)
    base_ss, model_ss = ss.spawn(2)
    total_steps = baseline_replicates * seeds + len(models) * seeds
    done = 0

    def tick(stage: str, d: int = 1) -> None:
        nonlocal done
        done += d
        if progress and (done % 25 == 0 or done >= total_steps):
            progress(min(done, total_steps), total_steps, stage)

    def run_set(weights: np.ndarray, rng: np.random.Generator) -> dict[str, np.ndarray]:
        return run_metrics(sample_tickets(weights, tickets, k, rng), Y, pay, prize_mask, simple_price)

    # ---- baseline: R réplicas, cada uma média de `seeds` execuções uniformes
    uni = np.full((test_contests, pool), 1.0 / pool)
    metric_keys = ("mean_hits_per_ticket", "tier_hit_rate", "return_ratio")
    base = {mk: np.empty((baseline_replicates, 3)) for mk in metric_keys}  # [total, metade1, metade2]
    base_rngs = [np.random.default_rng(s) for s in base_ss.spawn(baseline_replicates)]
    for r in range(baseline_replicates):
        acc = {mk: np.zeros(test_contests) for mk in metric_keys}
        for s in range(seeds):
            res = run_set(uni, np.random.default_rng(base_rngs[r].integers(2**63)))
            for mk in metric_keys:
                acc[mk] += res[mk] / seeds
            tick("baseline")
        for mk in metric_keys:
            a = acc[mk]
            base[mk][r] = (a.mean(), a[:half].mean(), a[half:].mean())

    results: list[dict[str, Any]] = []
    pvals: list[float] = []
    index: list[int] = []
    model_info: dict[str, Any] = {}
    model_seed_children = model_ss.spawn(len(models))
    for mi, model in enumerate(models):
        meta = MODEL_CATALOG[model]
        W, info = predict_matrix(h, model, tests, refit_every)
        model_info[model] = info
        seed_children = model_seed_children[mi].spawn(seeds)
        series = {mk: np.zeros(test_contests) for mk in metric_keys}
        per_seed = {mk: [] for mk in metric_keys}
        hits_total = np.zeros(k + 1)
        for s in range(seeds):
            res = run_set(W, np.random.default_rng(seed_children[s]))
            for mk in metric_keys:
                series[mk] += res[mk] / seeds
                per_seed[mk].append(float(res[mk].mean()))
            hits_total += res["_hits"]
            tick(f"modelo {model}")
        hyper = sps.hypergeom.pmf(np.arange(k + 1), pool, k, k)
        hits_payload = {"values": list(range(k + 1)), "observed": (hits_total / hits_total.sum()).tolist(), "expected": hyper.tolist(), "tickets_total": int(hits_total.sum())}
        for mk in metric_keys:
            a = series[mk]
            value, v1, v2 = float(a.mean()), float(a[:half].mean()), float(a[half:].mean())
            br = base[mk]
            p = float((1 + (br[:, 0] >= value).sum()) / (1 + baseline_replicates))
            ph = (float((1 + (br[:, 1] >= v1).sum()) / (1 + baseline_replicates)), float((1 + (br[:, 2] >= v2).sum()) / (1 + baseline_replicates)))
            se = _se(a)
            results.append(dict(model_name=model, metric_name=mk, value=value, ci_low=value - 1.96 * se, ci_high=value + 1.96 * se,
                                baseline_value=float(br[:, 0].mean()), baseline_ci_low=float(np.percentile(br[:, 0], 2.5)), baseline_ci_high=float(np.percentile(br[:, 0], 97.5)),
                                p_value=p, payload=dict(per_seed=per_seed[mk], halves={"first": {"value": v1, "p_value": ph[0]}, "second": {"value": v2, "p_value": ph[1]}},
                                                         higher_is_better=True, test_note="p unilateral vs distribuição nula do baseline uniforme (réplicas)",
                                                         **({"hits_distribution": hits_payload} if mk == "mean_hits_per_ticket" else {}), tickets=tickets, contests=test_contests)))
            pvals.append(p)
            index.append(len(results) - 1)
        if meta["probabilistic"]:
            L = prob_losses(W, Y)
            U = prob_losses(np.full((test_contests, pool), k / pool), Y)  # baseline probabilístico: p = k/N por dezena
            for mk in ("log_loss", "brier"):
                d = L[mk] - U[mk]
                se_d = _se(d)
                z = d.mean() / se_d if se_d > 0 else 0.0
                p = float(sps.norm.cdf(z))
                halves = []
                for sl in (slice(0, half), slice(half, None)):
                    dd = d[sl]
                    sed = _se(dd)
                    halves.append({"value": float(L[mk][sl].mean()), "p_value": float(sps.norm.cdf(dd.mean() / sed)) if sed > 0 else 1.0})
                se_v = _se(L[mk])
                results.append(dict(model_name=model, metric_name=mk, value=float(L[mk].mean()), ci_low=float(L[mk].mean() - 1.96 * se_v), ci_high=float(L[mk].mean() + 1.96 * se_v),
                                    baseline_value=float(U[mk].mean()), baseline_ci_low=float(U[mk].mean() - 1.96 * se_d), baseline_ci_high=float(U[mk].mean() + 1.96 * se_d),
                                    p_value=p, payload=dict(halves={"first": halves[0], "second": halves[1]}, higher_is_better=False,
                                                             test_note="teste z pareado por concurso da diferença de perda (modelo − uniforme); menor é melhor", paired_diff_mean=float(d.mean()), paired_diff_se=float(se_d))))
                pvals.append(p)
                index.append(len(results) - 1)
    qvals = benjamini_hochberg(np.array(pvals))
    for i, qv in zip(index, qvals):
        r = results[i]
        r["q_value"] = float(qv)
        hib = r["payload"]["higher_is_better"]
        ph = (r["payload"]["halves"]["first"]["p_value"], r["payload"]["halves"]["second"]["p_value"])
        r["verdict"] = verdict_for(r["value"], r["baseline_ci_low"], r["baseline_ci_high"], r["p_value"], float(qv), ph, hib)
    for r in results:
        r["payload"].pop("higher_is_better", None)
    n_h = len(results)
    conclusion = conclude(results, n_h, test_contests, tickets)
    meta = {
        "version": BACKTEST_VERSION, "seed": seed, "n_hypotheses": n_h, "train_cutoff_contest": int(contests[n - test_contests - 1]),
        "test_start_contest": int(contests[n - test_contests]), "test_end_contest": int(contests[-1]), "models": models, "model_info": model_info,
        "data_used": f"treino: concursos ≤ {int(contests[n - test_contests - 1])}; teste: {int(contests[n - test_contests])}–{int(contests[-1])} (walk-forward, só passado em cada concurso)",
        "expected_false_positives_at_05": 0.05 * n_h,
    }
    return clean({"results": results, "conclusion": conclusion, "meta": meta})


def conclude(results: list[dict[str, Any]], n_h: int, test_contests: int, tickets: int) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    limitations = [
        "Sorteios são independentes e uniformes: o histórico não altera a chance do próximo concurso. Qualquer 'vantagem' aparente é, a priori, ruído.",
        f"{n_h} hipóteses testadas (modelos × métricas); com α=0,05 esperam-se ≈{0.05 * n_h:.1f} falsos positivos sem correção — usamos Benjamini–Hochberg.",
        f"Período de teste: {test_contests} concursos; {tickets} bilhetes simples por concurso. Amostra pequena para prêmios raros: faixas altas quase nunca ocorrem.",
        "Retorno = prêmios históricos nominais por faixa (rateio do concurso) ÷ custo; assume que o rateio não mudaria com o seu bilhete; sem impostos; prêmio principal só conta se o rateio histórico existir.",
        "Bilhetes por modelo são sorteados proporcionalmente aos pesos do modelo (não é 'top-k determinístico'); duplicatas de bilhete no mesmo concurso são possíveis e desprezíveis.",
        "Random Forest/Boosting não foram executados: o baseline e a regressão logística regularizada já indicam se há sinal explorável; modelos mais flexíveis só sobreajustariam.",
    ]
    if counts.get("better_replicated"):
        verdict = "candidate_advantage_needs_replication"
        summary = ("Algum método superou o baseline de forma significativa e replicada nas duas metades do teste. Trate como hipótese a confirmar em dados NOVOS (fora da amostra); "
                   "não é evidência de previsibilidade, e não altera a probabilidade matemática de nenhum bilhete.")
    elif counts.get("better_significant_not_replicated") or counts.get("better_not_significant"):
        verdict = "inconclusive"
        summary = ("Alguns resultados ficaram numericamente acima do baseline, mas sem evidência robusta (não significativos após correção de múltiplas hipóteses "
                   "ou não replicados nas duas metades). Resultado compatível com acaso.")
    else:
        verdict = "no_evidence_of_advantage"
        summary = "Nenhum método foi melhor que o baseline aleatório de mesmo custo; diferenças são compatíveis com zero ou desfavoráveis. Esperado para sorteios justos."
    return {"verdict": verdict, "summary": summary, "limitations": limitations, "verdict_counts": counts}
