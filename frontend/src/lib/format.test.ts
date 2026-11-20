import { describe, expect, it } from 'vitest';
import { fmtBRL, fmtDate, fmtInt, fmtNum, fmtOneIn, fmtPct, fmtPValue, fmtProb, pad2 } from './format';

const nb = (s: string) => s.replace(/ | /g, ' ');

describe('formatadores pt-BR', () => {
  it('formata inteiros com separador de milhar', () => {
    expect(fmtInt(1234567)).toBe('1.234.567');
    expect(fmtInt('50063860')).toBe('50.063.860');
    expect(fmtInt(null)).toBe('—');
  });
  it('preserva precisão de inteiros muito grandes vindos como string', () => {
    expect(fmtInt('12345678901234567890')).toBe('12.345.678.901.234.567.890');
  });
  it('formata decimais com vírgula', () => {
    expect(fmtNum(3.14159, 2)).toBe('3,14');
    expect(fmtNum('abc')).toBe('—');
  });
  it('formata moeda em reais a partir de string', () => {
    expect(nb(fmtBRL('7534.97'))).toBe('R$ 7.534,97');
    expect(nb(fmtBRL(0))).toBe('R$ 0,00');
    expect(fmtBRL(undefined)).toBe('—');
  });
  it('formata percentuais', () => {
    expect(nb(fmtPct(0.0625, 2))).toBe('6,25%');
  });
  it('formata datas como dd/mm/aaaa sem deslocar o fuso', () => {
    expect(fmtDate('2026-11-19')).toBe('19/11/2026');
    expect(fmtDate(null)).toBe('—');
  });
  it('formata "1 em X" a partir da fração exata', () => {
    expect(fmtOneIn(3268760, { numerator: '1', denominator: '3268760' })).toBe('1 em 3.268.760');
    expect(fmtOneIn(null, { numerator: '150', denominator: '3268760' })).toBe('1 em 21.791,73');
    expect(fmtOneIn(11.4)).toBe('1 em 11,40');
  });
  it('formata probabilidades pequenas em notação científica', () => {
    expect(fmtProb(3.0592640634368994e-7)).toBe('3,059 × 10^-7');
    expect(nb(fmtProb(0.0877))).toBe('8,77%');
    expect(fmtProb(0)).toBe('0');
  });
  it('formata p-values', () => {
    expect(fmtPValue(0.00001)).toBe('< 0,0001');
    expect(fmtPValue(0.5433)).toBe('0,5433');
  });
  it('completa dezenas com zero à esquerda', () => {
    expect(pad2(7)).toBe('07');
    expect(pad2(60)).toBe('60');
  });
});
