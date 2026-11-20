import { describe, expect, it } from 'vitest';
import { Z_CAP, clampZ, volanteDims, volantePos, zColor, zIntensity, zTextColor } from './heatmap';

describe('escala do heatmap', () => {
  it('satura o z-score em ±3', () => {
    expect(clampZ(10)).toBe(Z_CAP);
    expect(clampZ(-10)).toBe(-Z_CAP);
    expect(clampZ(Number.NaN)).toBe(0);
  });
  it('intensidade é simétrica e normalizada', () => {
    expect(zIntensity(0)).toBe(0);
    expect(zIntensity(1.5)).toBeCloseTo(0.5);
    expect(zIntensity(-1.5)).toBeCloseTo(0.5);
    expect(zIntensity(99)).toBe(1);
  });
  it('usa matiz azul para z negativo e laranja para positivo', () => {
    expect(zColor(-2)).toMatch(/^hsl\(215 /);
    expect(zColor(2)).toMatch(/^hsl\(28 /);
  });
  it('quanto maior |z|, mais escura (claro) a célula', () => {
    const l = (c: string) => Number(/(\d+)%\)$/.exec(c)?.[1]);
    expect(l(zColor(3))).toBeLessThan(l(zColor(1)));
    expect(l(zColor(1))).toBeLessThan(l(zColor(0)));
  });
  it('no tema escuro a célula neutra é escura e as extremas mais claras', () => {
    const l = (c: string) => Number(/(\d+)%\)$/.exec(c)?.[1]);
    expect(l(zColor(0, true))).toBeLessThan(l(zColor(3, true)));
  });
  it('escolhe cor de texto legível', () => {
    expect(zTextColor(0)).toBe('#1b2330');
    expect(zTextColor(3)).toBe('#111');
    expect(zTextColor(3, true)).toBe('#fff');
  });
  it('mapeia dezenas para o volante', () => {
    expect(volantePos(1, 10)).toEqual({ row: 0, col: 0 });
    expect(volantePos(60, 10)).toEqual({ row: 5, col: 9 });
    expect(volantePos(25, 5)).toEqual({ row: 4, col: 4 });
  });
  it('dimensões do volante por modalidade', () => {
    expect(volanteDims('megasena')).toEqual({ rows: 6, cols: 10 });
    expect(volanteDims('lotofacil')).toEqual({ rows: 5, cols: 5 });
    expect(volanteDims('quina')).toEqual({ rows: 8, cols: 10 });
  });
});
