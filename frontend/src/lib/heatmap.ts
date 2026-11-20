// Escala divergente para z-scores do heatmap. |z| é saturado em Z_CAP.
export const Z_CAP = 3;

export function clampZ(z: number): number {
  if (!Number.isFinite(z)) return 0;
  return Math.max(-Z_CAP, Math.min(Z_CAP, z));
}

/** Intensidade 0..1 a partir de |z|. */
export function zIntensity(z: number): number {
  return Math.abs(clampZ(z)) / Z_CAP;
}

/** Cor HSL: azul (z<0) ↔ neutro ↔ laranja (z>0). Neutro em z≈0. */
export function zColor(z: number, dark = false): string {
  const t = zIntensity(z);
  const hue = z < 0 ? 215 : 28;
  const light = dark ? 22 + t * 30 : 96 - t * 46;
  const sat = 15 + t * 70;
  return 'hsl(' + hue + ' ' + sat.toFixed(0) + '% ' + light.toFixed(0) + '%)';
}

/** Cor de texto legível sobre zColor. */
export function zTextColor(z: number, dark = false): string {
  const t = zIntensity(z);
  if (dark) return t > 0.1 ? '#fff' : '#e6e9ef';
  return t > 0.6 ? '#111' : '#1b2330';
}

/** Posição (linha, coluna) 0-based de uma dezena no volante (dezena 1 = canto superior esquerdo). */
export function volantePos(n: number, cols: number): { row: number; col: number } {
  const i = n - 1;
  return { row: Math.floor(i / cols), col: i % cols };
}

export function volanteDims(lottery: string): { rows: number; cols: number } {
  if (lottery === 'lotofacil') return { rows: 5, cols: 5 };
  if (lottery === 'quina') return { rows: 8, cols: 10 };
  return { rows: 6, cols: 10 };
}
