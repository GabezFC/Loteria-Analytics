"""Motor estatístico determinístico (NumPy/SciPy). Sem acesso a banco: recebe a matriz de sorteios.

Tudo aqui é DESCRITIVO ou INFERENCIAL sobre o passado. Nenhuma saída é probabilidade de um
resultado futuro: sorteios justos são independentes e uniformes. Cada teste declara hipótese nula,
tamanho amostral e limitações. Simulações usam semente registrada (reprodutível bit a bit).
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from itertools import combinations
from typing import Any

import numpy as np
from scipy import stats as sps

STATS_VERSION = "stats-v1"
WINDOWS: list[tuple[str, int | None]] = [("30", 30), ("100", 100), ("300", 300), ("1000", 1000), ("all", None)]
MIN_INFERENCE_N = 100
MIN_COMBO_N = 300
MAX_ENUMERATIONS = 2_500_000
TOP_COMBOS = 100


# ---------------------------------------------------------------- utilidades
def indicator(draws: np.ndarray, pool: int) -> np.ndarray:
    """(n,k) dezenas 1..N -> matriz booleana (n,N)."""
    m = np.zeros((draws.shape[0], pool), dtype=bool)
    np.put_along_axis(m, draws - 1, True, axis=1)
    return m


def fingerprint(contests: np.ndarray, draws: np.ndarray) -> str:
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(contests, dtype=np.int64).tobytes())
    h.update(np.ascontiguousarray(draws, dtype=np.int16).tobytes())
    return h.hexdigest()


def wilson(successes: np.ndarray, n: int, z: float = 1.959963984540054) -> tuple[np.ndarray, np.ndarray]:
    p = successes / n
    d = 1 + z * z / n
    center = (p + z * z / (2 * n)) / d
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return center - half, center + half


def benjamini_hochberg(p: np.ndarray, total_tests: int | None = None) -> np.ndarray:
    """q-values de Benjamini–Hochberg. `total_tests` > len(p) assume os testes ausentes com p=1."""
    m = int(total_tests or len(p))
    order = np.argsort(p, kind="stable")
    ranked = p[order] * m / (np.arange(len(p)) + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty_like(q)
    out[order] = np.minimum(q, 1.0)
    return out


def _merge_small_bins(obs: np.ndarray, exp: np.ndarray, minimum: float = 5.0) -> tuple[np.ndarray, np.ndarray]:
    """Agrupa classes adjacentes (da esquerda para a direita) até a frequência esperada >= minimum."""
    o: list[float] = []
    e: list[float] = []
    acc_o = acc_e = 0.0
    for a, b in zip(obs, exp):
        acc_o += float(a)
        acc_e += float(b)
        if acc_e >= minimum:
            o.append(acc_o)
            e.append(acc_e)
            acc_o = acc_e = 0.0
    if acc_e > 0:
        if e:
            o[-1] += acc_o
            e[-1] += acc_e
        else:
            o.append(acc_o)
            e.append(acc_e)
    return np.array(o), np.array(e)


def gof(obs: np.ndarray, exp: np.ndarray) -> dict[str, Any]:
    o, e = _merge_small_bins(obs, exp)
    if len(e) < 2:
        return {"chi2": None, "df": 0, "p_value": None, "note": "classes insuficientes (frequência esperada < 5)"}
    chi2 = float(((o - e) ** 2 / e).sum())
    df = len(e) - 1
    return {"chi2": chi2, "df": df, "p_value": float(sps.chi2.sf(chi2, df))}


def _num(x: Any) -> Any:
    if isinstance(x, (np.floating,)):
        f = float(x)
        return f if math.isfinite(f) else None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    return x


def clean(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return clean(obj.tolist())
    return _num(obj)


# ---------------------------------------------------------------- por dezena
def number_stats(m: np.ndarray, pool: int, k: int) -> list[dict[str, Any]]:
    n = m.shape[0]
    p = k / pool
    freq = m.sum(axis=0)
    expected = n * p
    sd = math.sqrt(n * p * (1 - p))
    z = (freq - expected) / sd
    lo, hi = wilson(freq, n)
    rows = []
    for j in range(pool):
        idx = np.flatnonzero(m[:, j])
        current = int(n - 1 - idx[-1]) if idx.size else n
        if idx.size:
            gaps_abs = np.diff(np.concatenate(([-1], idx, [n])))  - 1  # ausências consecutivas, incl. bordas
            max_delay = int(gaps_abs.max())
        else:
            max_delay = n
        mean_gap = float(np.diff(idx).mean()) if idx.size > 1 else None
        rows.append({
            "number": j + 1, "frequency": int(freq[j]), "relative_frequency": float(freq[j] / n), "expected_frequency": float(expected),
            "z_score": float(z[j]), "ci_low": float(lo[j]), "ci_high": float(hi[j]), "current_delay": current, "max_delay": max_delay,
            "mean_gap": mean_gap,
            "metadata": {"expected_relative": p, "expected_mean_gap": 1 / p},
        })
    return rows


# ---------------------------------------------------------------- distribuições
def _hyper_expected(pool: int, k: int, subset: int, n: int) -> np.ndarray:
    xs = np.arange(0, k + 1)
    return n * sps.hypergeom.pmf(xs, pool, subset, k)


def _count_dist(counts: np.ndarray, pool: int, k: int, subset: int) -> dict[str, Any]:
    n = len(counts)
    obs = np.bincount(counts, minlength=k + 1).astype(float)
    exp = _hyper_expected(pool, k, subset, n)
    return {"values": list(range(k + 1)), "observed": obs, "expected": exp, "gof": gof(obs, exp),
            "mean": float(counts.mean()), "expected_mean": k * subset / pool}


def draw_distributions(draws: np.ndarray, m: np.ndarray, pool: int, k: int) -> dict[str, Any]:
    n = draws.shape[0]
    sums = draws.sum(axis=1)
    exp_mean = k * (pool + 1) / 2
    exp_var = k * (pool + 1) * (pool - k) / 12
    hist_counts, edges = np.histogram(sums, bins=min(24, max(5, int(np.sqrt(n)))))
    out: dict[str, Any] = {
        "sum": {
            "mean": sums.mean(), "median": float(np.median(sums)), "std": sums.std(ddof=1) if n > 1 else 0.0, "variance": sums.var(ddof=1) if n > 1 else 0.0,
            "min": int(sums.min()), "max": int(sums.max()), "range": int(sums.max() - sums.min()),
            "expected_mean": exp_mean, "expected_variance": exp_var,
            "histogram": {"edges": edges, "counts": hist_counts},
        }
    }
    evens = (draws % 2 == 0).sum(axis=1)
    out["parity"] = {"evens_per_draw": _count_dist(evens, pool, k, pool // 2), "note": "pares no universo = N//2"}
    low = (draws <= pool // 2).sum(axis=1)
    out["low_high"] = {"low_per_draw": _count_dist(low, pool, k, pool // 2), "note": f"baixas = 1..{pool // 2}"}
    groups = []
    for start in range(1, pool + 1, 10):
        end = min(start + 9, pool)
        size = end - start + 1
        mean = float(((draws >= start) & (draws <= end)).sum(axis=1).mean())
        groups.append({"range": [start, end], "mean_per_draw": mean, "expected_mean_per_draw": k * size / pool})
    out["groups_of_ten"] = groups
    cols = 5 if pool == 25 else 10
    rows_n = pool // cols
    zero = draws - 1
    row_means = [float((zero // cols == r).sum(axis=1).mean()) for r in range(rows_n)]
    col_means = [float((zero % cols == c).sum(axis=1).mean()) for c in range(cols)]
    out["volante"] = {"rows": rows_n, "columns": cols, "row_mean_per_draw": row_means, "column_mean_per_draw": col_means,
                      "expected_row_mean": k * cols / pool, "expected_column_mean": k * rows_n / pool}
    diffs = np.diff(draws, axis=1)
    consecutive = (diffs == 1).sum(axis=1)
    cmax = int(consecutive.max()) if n else 0
    out["consecutive"] = {"pairs_per_draw_distribution": {"values": list(range(cmax + 1)), "observed": np.bincount(consecutive, minlength=cmax + 1)},
                          "mean": float(consecutive.mean()), "expected_mean": k * (k - 1) / pool}
    out["spacing"] = {"mean_adjacent_distance": float(diffs.mean()), "max_adjacent_distance_mean": float(diffs.max(axis=1).mean()),
                      "span_mean": float((draws[:, -1] - draws[:, 0]).mean()),
                      "note": "medidas meramente descritivas de dispersão no volante"}
    if n > 1:
        rep = (m[1:] & m[:-1]).sum(axis=1)
        out["repeated_from_previous"] = _count_dist(rep, pool, k, k)
    # intervalos entre aparições (todas as dezenas) vs geométrica esperada
    gaps: list[np.ndarray] = []
    for j in range(pool):
        idx = np.flatnonzero(m[:, j])
        if idx.size > 1:
            gaps.append(np.diff(idx))
    if gaps:
        allg = np.concatenate(gaps)
        p = k / pool
        bins = np.arange(1, min(int(allg.max()), 40) + 2)
        obs = np.array([(allg == b).sum() for b in bins[:-1]] + [(allg >= bins[-1]).sum()], dtype=float)
        pm = (1 - p) ** (bins[:-1] - 1) * p
        exp = np.concatenate((pm, [(1 - p) ** (bins[-1] - 1)])) * allg.size
        out["appearance_gaps"] = {"bins": [int(b) for b in bins[:-1]] + [f">={int(bins[-1])}"], "observed": obs, "expected_geometric": exp,
                                  "mean": float(allg.mean()), "expected_mean": 1 / p, "max": int(allg.max()), "sample_size": int(allg.size)}
    return out


# ---------------------------------------------------------------- combinações
def combination_stats(draws: np.ndarray, m: np.ndarray, pool: int, k: int, top: int = TOP_COMBOS) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    n = draws.shape[0]
    rows: list[dict[str, Any]] = []
    meta: dict[str, Any] = {"sizes": {}, "multiple_comparisons": "Benjamini–Hochberg por tamanho; combinações nunca observadas (tamanho>=3) tratadas com p=1 (conservador)"}
    for s in (2, 3, 4):
        if s > k:
            continue
        total = math.comb(pool, s)
        if s >= 3 and n * math.comb(k, s) > MAX_ENUMERATIONS:
            meta["sizes"][str(s)] = {"skipped": True, "reason": f"enumeração {n * math.comb(k, s)} > limite {MAX_ENUMERATIONS}"}
            continue
        prob = math.prod((k - i) / (pool - i) for i in range(s))
        if s == 2:
            co = m.T.astype(np.int32) @ m.astype(np.int32)
            iu = np.triu_indices(pool, 1)
            observed = co[iu].astype(np.int64)
            combos = [(int(a) + 1, int(b) + 1) for a, b in zip(*iu)]
        else:
            counter: Counter = Counter()
            for row in draws:
                counter.update(combinations(row.tolist(), s))
            combos = list(counter.keys())
            observed = np.fromiter(counter.values(), dtype=np.int64, count=len(combos))
        up = sps.binom.sf(observed - 1, n, prob)
        low = sps.binom.cdf(observed, n, prob)
        pvals = np.minimum(1.0, 2 * np.minimum(up, low))
        qvals = benjamini_hochberg(pvals, total)
        expected = n * prob
        z = (observed - expected) / math.sqrt(n * prob * (1 - prob))
        meta["sizes"][str(s)] = {"tested": len(combos), "possible": total, "expected_count": expected, "significant_q05": int((qvals < 0.05).sum()),
                                 "expected_false_positives_at_05": 0.05 * total}
        order = np.argsort(-z)
        picks = list(order[:top]) + list(order[::-1][:top])
        seen: set[int] = set()
        for i in picks:
            if int(i) in seen:
                continue
            seen.add(int(i))
            rows.append({"combo_size": s, "numbers": list(combos[i]), "observed": int(observed[i]), "expected": float(expected),
                         "lift": float(observed[i] / expected), "z_score": float(z[i]), "p_value": float(pvals[i]), "q_value": float(qvals[i]), "sample_size": n})
    return rows, meta


# ---------------------------------------------------------------- inferência
def _null_freq_sims(n: int, pool: int, k: int, sims: int, rng: np.random.Generator) -> np.ndarray:
    out = np.empty((sims, pool), dtype=np.int64)
    chunk = max(1, int(2_000_000 // max(1, n * pool)))
    done = 0
    while done < sims:
        c = min(chunk, sims - done)
        r = rng.random((c, n, pool), dtype=np.float32)
        idx = np.argpartition(r, k - 1, axis=2)[:, :, :k]
        for t in range(c):
            out[done + t] = np.bincount(idx[t].ravel(), minlength=pool)
        done += c
    return out


def _entropy(freq: np.ndarray) -> np.ndarray:
    q = freq / freq.sum(axis=-1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(q > 0, q * np.log2(q), 0.0)
    return -t.sum(axis=-1)


def _jsd(a: np.ndarray, b: np.ndarray) -> float:
    pa, pb = a / a.sum(), b / b.sum()
    mix = (pa + pb) / 2
    def kl(x, y):
        mask = x > 0
        return float((x[mask] * np.log2(x[mask] / y[mask])).sum())
    return 0.5 * kl(pa, mix) + 0.5 * kl(pb, mix)


def _lag1_z(x: np.ndarray) -> np.ndarray:
    """z da autocorrelação de lag 1 por coluna (x: n×c); sob H0, r ≈ N(0, 1/n)."""
    n = x.shape[0]
    xc = x - x.mean(axis=0)
    den = (xc ** 2).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = (xc[1:] * xc[:-1]).sum(axis=0) / den
    return np.nan_to_num(r) * math.sqrt(n)


def inference(draws: np.ndarray, m: np.ndarray, pool: int, k: int, rng: np.random.Generator, sims: int, perms: int) -> dict[str, Any]:
    n = draws.shape[0]
    p = k / pool
    freq = m.sum(axis=0).astype(float)
    exp = n * p
    out: dict[str, Any] = {"sample_size": n, "seed_note": "simulações seedadas; resultado reproduzível com os mesmos dados e parâmetros"}

    stat = float(((freq - exp) ** 2 / (n * p * (1 - p))).sum() * (pool - 1) / pool)
    sim_f = _null_freq_sims(n, pool, k, sims, rng)
    sim_stat = ((sim_f - exp) ** 2 / (n * p * (1 - p))).sum(axis=1) * (pool - 1) / pool
    out["chi_square_uniformity"] = {
        "null_hypothesis": "cada dezena tem a mesma probabilidade k/N em cada concurso (sorteio uniforme sem reposição)",
        "statistic": stat, "df": pool - 1, "p_value_asymptotic": float(sps.chi2.sf(stat, pool - 1)),
        "p_value_monte_carlo": float((1 + (sim_stat >= stat).sum()) / (1 + sims)), "simulations": sims,
        "method_note": "estatística de Pearson com correção (N-1)/(N-k) para sorteio sem reposição (dezenas negativamente correlacionadas no mesmo concurso)",
        "limitation": "rejeição indica desvio da uniformidade na amostra, não permite prever o próximo concurso",
    }
    h = float(_entropy(freq))
    h_sim = _entropy(sim_f.astype(float))
    out["entropy"] = {
        "null_hypothesis": "distribuição de frequências compatível com sorteio uniforme", "bits": h, "max_bits": math.log2(pool), "normalized": h / math.log2(pool),
        "null_mean_bits": float(h_sim.mean()), "null_std_bits": float(h_sim.std(ddof=1)),
        "p_value_lower_tail": float((1 + (h_sim <= h).sum()) / (1 + sims)), "simulations": sims,
    }

    xs = m.astype(float)
    z_ac = _lag1_z(xs)
    p_ac = 2 * sps.norm.sf(np.abs(z_ac))
    q_ac = benjamini_hochberg(p_ac)
    obs_max = float(np.abs(z_ac).max())
    perm_max = np.empty(perms)
    for i in range(perms):
        perm_max[i] = np.abs(_lag1_z(xs[rng.permutation(n)])).max()
    out["autocorrelation_lag1"] = {
        "null_hypothesis": "presença de cada dezena é independente entre concursos consecutivos", "tests": pool,
        "significant_q05": int((q_ac < 0.05).sum()), "expected_false_positives_at_05": 0.05 * pool, "max_abs_z": obs_max,
        "p_value_permutation_max_abs_z": float((1 + (perm_max >= obs_max).sum()) / (1 + perms)), "permutations": perms,
        "per_number": [{"number": j + 1, "z": float(z_ac[j]), "p_value": float(p_ac[j]), "q_value": float(q_ac[j])} for j in range(pool)],
    }

    sums = draws.sum(axis=1).astype(float)
    lags = min(10, max(1, n // 5))
    sc = sums - sums.mean()
    den = float((sc ** 2).sum())
    rho = np.array([float((sc[h_:] * sc[:-h_]).sum() / den) for h_ in range(1, lags + 1)])
    ljung = float(n * (n + 2) * (rho ** 2 / (n - np.arange(1, lags + 1))).sum())
    out["sum_ljung_box"] = {"null_hypothesis": "soma dos concursos é ruído branco (sem autocorrelação até o lag testado)", "lags": lags,
                            "acf": rho, "statistic": ljung, "p_value": float(sps.chi2.sf(ljung, lags))}

    med = np.median(sums)
    sign = sums[sums != med] > med
    if sign.size > 10 and 0 < sign.sum() < sign.size:
        n1, n2 = int(sign.sum()), int((~sign).sum())
        runs = 1 + int((sign[1:] != sign[:-1]).sum())
        mu = 2 * n1 * n2 / (n1 + n2) + 1
        var = (mu - 1) * (mu - 2) / (n1 + n2 - 1)
        zr = (runs - mu) / math.sqrt(var) if var > 0 else 0.0
        out["runs_test_sum"] = {"null_hypothesis": "ordem acima/abaixo da mediana da soma é aleatória", "runs": runs, "expected_runs": mu, "z": zr, "p_value": float(2 * sps.norm.sf(abs(zr)))}

    if n >= 2 * MIN_INFERENCE_N:
        h1, h2 = freq_half(m)
        jsd = _jsd(h1, h2)
        mask = m
        perm_j = np.empty(perms)
        half = n // 2
        for i in range(perms):
            pm = mask[rng.permutation(n)]
            perm_j[i] = _jsd(pm[:half].sum(axis=0).astype(float), pm[half:].sum(axis=0).astype(float))
        out["window_stability"] = {"null_hypothesis": "metades inicial e final têm a mesma distribuição de frequências", "jsd_bits": jsd,
                                   "p_value_permutation": float((1 + (perm_j >= jsd).sum()) / (1 + perms)), "permutations": perms}

    seg = max(10, n // 10)
    if n >= 2 * seg + 10:
        x = (sums - sums.mean()) / (sums.std() or 1.0)
        def cusum(v):
            s = np.cumsum(v - v.mean())
            return np.abs(s[seg:-seg]) / math.sqrt(len(v)), s
        stat_c, s_all = cusum(x)
        best = int(np.argmax(stat_c)) + seg
        obs = float(stat_c.max())
        pc = np.empty(perms)
        for i in range(perms):
            pc[i] = cusum(x[rng.permutation(n)])[0].max()
        out["change_point_sum"] = {"null_hypothesis": "a média da soma é constante ao longo do tempo", "candidate_index": best, "statistic": obs,
                                   "p_value_permutation": float((1 + (pc >= obs).sum()) / (1 + perms)), "permutations": perms,
                                   "note": "um candidato por série; p-value por permutação controla falsos positivos sob exchangeabilidade"}
    return out


def freq_half(m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    half = m.shape[0] // 2
    return m[:half].sum(axis=0).astype(float), m[half:].sum(axis=0).astype(float)


# ---------------------------------------------------------------- orquestração
def analyze_window(contests: np.ndarray, draws: np.ndarray, pool: int, k: int, seed: int, sims: int = 200, perms: int = 300) -> dict[str, Any]:
    n = draws.shape[0]
    m = indicator(draws, pool)
    rng = np.random.default_rng(seed)
    result: dict[str, Any] = {
        "number_stats": number_stats(m, pool, k),
        "distributions": draw_distributions(draws, m, pool, k),
        "combinations": [], "combination_meta": {"skipped": True, "reason": f"janela < {MIN_COMBO_N} concursos"},
        "inference": None,
    }
    if n >= MIN_COMBO_N:
        result["combinations"], result["combination_meta"] = combination_stats(draws, m, pool, k)
    if n >= MIN_INFERENCE_N:
        result["inference"] = inference(draws, m, pool, k, rng, sims, perms)
    result["meta"] = {
        "sample_size": n, "first_contest": int(contests[0]), "last_contest": int(contests[-1]), "stats_version": STATS_VERSION, "seed": seed,
        "disclaimer": "Estatísticas descritivas/inferenciais do passado. Não representam probabilidade de resultados futuros; sorteios são independentes.",
        "inference_available": n >= MIN_INFERENCE_N, "combinations_available": n >= MIN_COMBO_N,
    }
    return clean(result)
