// Formatadores pt-BR. Valores monetários/inteiros grandes chegam como string da API.
const nf0 = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });
const brl = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });

export const DASH = '—';

function toNum(v: number | string | null | undefined): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

export function fmtInt(v: number | string | null | undefined): string {
  if (typeof v === 'string' && /^\d{16,}$/.test(v)) {
    // inteiro grande: agrupa por milhar sem perder precisão
    return v.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  }
  const n = toNum(v);
  return n === null ? DASH : nf0.format(n);
}

export function fmtNum(v: number | string | null | undefined, digits = 2): string {
  const n = toNum(v);
  if (n === null) return DASH;
  return new Intl.NumberFormat('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
}

export function fmtBRL(v: number | string | null | undefined): string {
  const n = toNum(v);
  return n === null ? DASH : brl.format(n);
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  return new Intl.NumberFormat('pt-BR', { style: 'percent', minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
}

/** Probabilidades pequenas: notação científica legível quando < 0,0001. */
export function fmtProb(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  if (v === 0) return '0';
  if (v < 0.0001) {
    const [m, e] = v.toExponential(3).split('e');
    return new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 3 }).format(Number(m)) + ' × 10^' + Number(e);
  }
  return fmtPct(v, v < 0.01 ? 4 : 2);
}

export function fmtPValue(p: number | null | undefined): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return DASH;
  if (p < 0.0001) return '< 0,0001';
  return fmtNum(p, 4);
}

/** "1 em X" com X inteiro agrupado (aceita fração exata como strings). */
export function fmtOneIn(oneIn: number | null | undefined, frac?: { numerator: string; denominator: string }): string {
  if (frac && /^\d+$/.test(frac.numerator) && /^\d+$/.test(frac.denominator) && frac.numerator !== '0') {
    try {
      const n = BigInt(frac.numerator);
      const d = BigInt(frac.denominator);
      const whole = (d * 100n) / n; // 2 casas
      const intPart = whole / 100n;
      const dec = whole % 100n;
      const base = fmtInt(intPart.toString());
      return dec === 0n ? '1 em ' + base : '1 em ' + base + ',' + dec.toString().padStart(2, '0');
    } catch {
      /* cai para one_in */
    }
  }
  if (oneIn === null || oneIn === undefined || !Number.isFinite(oneIn)) return DASH;
  return '1 em ' + (oneIn >= 100 ? fmtInt(Math.round(oneIn)) : fmtNum(oneIn, 2));
}

export function fmtFraction(f: { numerator: string; denominator: string }): string {
  return fmtInt(f.numerator) + ' / ' + fmtInt(f.denominator);
}

/** Data AAAA-MM-DD ou ISO → dd/mm/aaaa (sem deslocamento de fuso para datas puras). */
export function fmtDate(v: string | null | undefined): string {
  if (!v) return DASH;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  if (m) return m[3] + '/' + m[2] + '/' + m[1];
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleDateString('pt-BR');
}

export function fmtDateTime(v: string | null | undefined): string {
  if (!v) return DASH;
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
}

export function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

export function fmtSigned(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  return (v > 0 ? '+' : '') + fmtNum(v, digits);
}
