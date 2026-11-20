/** Aproximação de erf (Abramowitz–Stegun 7.1.26), erro < 1,5e-7. */
export function erf(x: number): number {
  const s = x < 0 ? -1 : 1;
  const ax = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * ax);
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-ax * ax);
  return s * y;
}

export function normalCdf(x: number, mean: number, std: number): number {
  if (std <= 0) return x < mean ? 0 : 1;
  return 0.5 * (1 + erf((x - mean) / (std * Math.SQRT2)));
}

/** Contagens esperadas por bin do histograma sob aproximação normal (N sorteios). */
export function expectedBinCounts(edges: number[], n: number, mean: number, variance: number): number[] {
  const std = Math.sqrt(variance);
  const out: number[] = [];
  for (let i = 0; i < edges.length - 1; i++) {
    out.push(n * (normalCdf(edges[i + 1] as number, mean, std) - normalCdf(edges[i] as number, mean, std)));
  }
  return out;
}
