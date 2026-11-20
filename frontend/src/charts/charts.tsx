import { useId, useState } from 'react';
import { extent, linear, niceTicks } from '../lib/scale';
import { clampZ, zColor, zTextColor } from '../lib/heatmap';
import { fmtNum } from '../lib/format';

type Fmt = (v: number) => string;
const defaultFmt: Fmt = (v) => fmtNum(v, Math.abs(v) >= 100 ? 0 : 2);

interface FrameProps {
  title: string;
  desc?: string;
  width: number;
  height: number;
  children: React.ReactNode;
}

function Frame({ title, desc, width, height, children }: FrameProps) {
  const id = useId();
  return (
    <svg
      className="chart"
      viewBox={'0 0 ' + width + ' ' + height}
      role="img"
      aria-labelledby={id + '-t'}
      aria-describedby={desc ? id + '-d' : undefined}
    >
      <title id={id + '-t'}>{title}</title>
      {desc && <desc id={id + '-d'}>{desc}</desc>}
      {children}
    </svg>
  );
}

interface Margin {
  l: number;
  r: number;
  t: number;
  b: number;
}

function YAxis({ ticks, y, m, w, fmt }: { ticks: number[]; y: (v: number) => number; m: Margin; w: number; fmt: Fmt }) {
  return (
    <g className="axis">
      {ticks.map((t) => (
        <g key={t}>
          <line className="grid" x1={m.l} x2={w - m.r} y1={y(t)} y2={y(t)} />
          <text x={m.l - 6} y={y(t)} textAnchor="end" dominantBaseline="middle">
            {fmt(t)}
          </text>
        </g>
      ))}
    </g>
  );
}

// ---------- Barras com banda de incerteza e linha de expectativa ----------
export interface BarBandDatum {
  label: string;
  value: number;
  low?: number;
  high?: number;
  tip?: string;
}

export function BarBandChart({
  data,
  expected,
  title,
  fmt = defaultFmt,
  yLabel,
}: {
  data: BarBandDatum[];
  expected?: number;
  title: string;
  fmt?: Fmt;
  yLabel?: string;
}) {
  const W = 760;
  const H = 280;
  const m: Margin = { l: 52, r: 12, t: 12, b: 28 };
  const vals = data.flatMap((d) => [d.value, d.low ?? d.value, d.high ?? d.value, expected ?? d.value]);
  const [lo, hi] = extent(vals);
  const y0 = Math.min(0, lo);
  const y1 = hi * 1.05 || 1;
  const y = linear(y0, y1, H - m.b, m.t);
  const n = Math.max(1, data.length);
  const bw = (W - m.l - m.r) / n;
  const ticks = niceTicks(y0, y1, 5);
  const every = n > 40 ? 5 : n > 20 ? 2 : 1;
  return (
    <Frame title={title} width={W} height={H} desc={'Barras por item com intervalo de confiança' + (expected !== undefined ? ' e linha de expectativa' : '')}>
      <YAxis ticks={ticks} y={y} m={m} w={W} fmt={fmt} />
      {yLabel && (
        <text className="axis-label" x={4} y={m.t + 4} fontSize="10">
          {yLabel}
        </text>
      )}
      {data.map((d, i) => {
        const x = m.l + i * bw;
        const cx = x + bw / 2;
        return (
          <g key={d.label + i}>
            <rect className="bar" x={x + bw * 0.12} width={bw * 0.76} y={y(Math.max(d.value, 0))} height={Math.max(0.5, Math.abs(y(d.value) - y(0)))}>
              <title>{d.tip ?? d.label + ': ' + fmt(d.value)}</title>
            </rect>
            {d.low !== undefined && d.high !== undefined && (
              <g className="band">
                <line x1={cx} x2={cx} y1={y(d.low)} y2={y(d.high)} />
                <line x1={cx - bw * 0.2} x2={cx + bw * 0.2} y1={y(d.low)} y2={y(d.low)} />
                <line x1={cx - bw * 0.2} x2={cx + bw * 0.2} y1={y(d.high)} y2={y(d.high)} />
              </g>
            )}
            {i % every === 0 && (
              <text className="axis" x={cx} y={H - 10} textAnchor="middle" fontSize={bw < 14 ? 8 : 10}>
                {d.label}
              </text>
            )}
          </g>
        );
      })}
      {expected !== undefined && (
        <g>
          <line className="expected" x1={m.l} x2={W - m.r} y1={y(expected)} y2={y(expected)} />
          <text className="expected-label" x={W - m.r - 2} y={y(expected) - 4} textAnchor="end" fontSize="10">
            esperado {fmt(expected)}
          </text>
        </g>
      )}
    </Frame>
  );
}

// ---------- Barras categóricas: observado × esperado ----------
export function CategoryBars({
  labels,
  observed,
  expected,
  title,
  fmt = defaultFmt,
  observedName = 'Observado',
  expectedName = 'Esperado',
}: {
  labels: string[];
  observed: number[];
  expected?: number[];
  title: string;
  fmt?: Fmt;
  observedName?: string;
  expectedName?: string;
}) {
  const W = 520;
  const H = 220;
  const m: Margin = { l: 52, r: 10, t: 14, b: 26 };
  const [, hi] = extent([...observed, ...(expected ?? [])]);
  const y = linear(0, hi * 1.08 || 1, H - m.b, m.t);
  const n = Math.max(1, labels.length);
  const gw = (W - m.l - m.r) / n;
  const ticks = niceTicks(0, hi * 1.08 || 1, 4);
  return (
    <div>
      <Frame title={title} width={W} height={H} desc={observedName + ' contra ' + expectedName}>
        <YAxis ticks={ticks} y={y} m={m} w={W} fmt={fmt} />
        {labels.map((l, i) => {
          const x = m.l + i * gw;
          const o = observed[i] ?? 0;
          const e = expected?.[i];
          return (
            <g key={l}>
              <rect className="bar" x={x + gw * 0.12} width={gw * 0.36} y={y(o)} height={Math.max(0.5, y(0) - y(o))}>
                <title>{l + ' — ' + observedName + ': ' + fmt(o)}</title>
              </rect>
              {e !== undefined && (
                <rect className="bar-alt" x={x + gw * 0.52} width={gw * 0.36} y={y(e)} height={Math.max(0.5, y(0) - y(e))}>
                  <title>{l + ' — ' + expectedName + ': ' + fmt(e)}</title>
                </rect>
              )}
              <text className="axis" x={x + gw / 2} y={H - 8} textAnchor="middle" fontSize="10">
                {l}
              </text>
            </g>
          );
        })}
      </Frame>
      <Legend items={[{ cls: 'sw-bar', name: observedName }, ...(expected ? [{ cls: 'sw-alt', name: expectedName }] : [])]} />
    </div>
  );
}

export function Legend({ items }: { items: { cls: string; name: string }[] }) {
  return (
    <ul className="legend" aria-label="Legenda">
      {items.map((i) => (
        <li key={i.name}>
          <span className={'swatch ' + i.cls} aria-hidden="true" /> {i.name}
        </li>
      ))}
    </ul>
  );
}

// ---------- Histograma com marcadores/curva esperada ----------
export function Histogram({
  edges,
  counts,
  title,
  markers = [],
  expectedCounts,
  fmt = defaultFmt,
}: {
  edges: number[];
  counts: number[];
  title: string;
  markers?: { value: number; label: string }[];
  expectedCounts?: number[];
  fmt?: Fmt;
}) {
  const W = 640;
  const H = 240;
  const m: Margin = { l: 52, r: 12, t: 14, b: 30 };
  if (edges.length < 2 || counts.length === 0) return <p className="muted">Sem dados para o histograma.</p>;
  const x = linear(edges[0] as number, edges[edges.length - 1] as number, m.l, W - m.r);
  const [, hi] = extent([...counts, ...(expectedCounts ?? [])]);
  const y = linear(0, hi * 1.08 || 1, H - m.b, m.t);
  const ticks = niceTicks(0, hi * 1.08 || 1, 4);
  const xt = niceTicks(edges[0] as number, edges[edges.length - 1] as number, 6);
  const curve =
    expectedCounts && expectedCounts.length === counts.length
      ? expectedCounts
          .map((v, i) => (i === 0 ? 'M' : 'L') + x(((edges[i] as number) + (edges[i + 1] as number)) / 2).toFixed(1) + ' ' + y(v).toFixed(1))
          .join(' ')
      : null;
  return (
    <div>
      <Frame title={title} width={W} height={H} desc="Histograma de frequências">
        <YAxis ticks={ticks} y={y} m={m} w={W} fmt={fmt} />
        {counts.map((c, i) => {
          const x0 = x(edges[i] as number);
          const x1 = x(edges[i + 1] as number);
          return (
            <rect key={i} className="bar" x={x0 + 0.5} width={Math.max(0.5, x1 - x0 - 1)} y={y(c)} height={Math.max(0.5, y(0) - y(c))}>
              <title>{'[' + fmt(edges[i] as number) + ', ' + fmt(edges[i + 1] as number) + '): ' + fmt(c)}</title>
            </rect>
          );
        })}
        {curve && <path className="curve" d={curve} fill="none" />}
        {markers.map((mk) => (
          <g key={mk.label}>
            <line className="expected" x1={x(mk.value)} x2={x(mk.value)} y1={m.t} y2={H - m.b} />
            <text className="expected-label" x={x(mk.value) + 3} y={m.t + 8} fontSize="10">
              {mk.label}
            </text>
          </g>
        ))}
        <g className="axis">
          {xt.map((t) => (
            <text key={t} x={x(t)} y={H - 10} textAnchor="middle" fontSize="10">
              {fmt(t)}
            </text>
          ))}
        </g>
      </Frame>
      {curve && <Legend items={[{ cls: 'sw-bar', name: 'Observado' }, { cls: 'sw-curve', name: 'Esperado' }]} />}
    </div>
  );
}

// ---------- Heatmap do volante ----------
export interface HeatCell {
  n: number;
  z: number;
  detail: string;
}

export function Heatmap({
  cells,
  rows,
  cols,
  dark,
  label,
}: {
  cells: HeatCell[];
  rows: number;
  cols: number;
  dark: boolean;
  label: string;
}) {
  const [active, setActive] = useState<HeatCell | null>(null);
  const size = 46;
  const gap = 4;
  const W = cols * (size + gap) + gap;
  const H = rows * (size + gap) + gap;
  return (
    <div>
      <svg className="chart heatmap" viewBox={'0 0 ' + W + ' ' + H} role="group" aria-label={label}>
        {cells.map((c) => {
          const i = c.n - 1;
          const cx = gap + (i % cols) * (size + gap);
          const cy = gap + Math.floor(i / cols) * (size + gap);
          return (
            <g
              key={c.n}
              tabIndex={0}
              role="img"
              aria-label={c.detail}
              onMouseEnter={() => setActive(c)}
              onFocus={() => setActive(c)}
              onMouseLeave={() => setActive(null)}
              onBlur={() => setActive(null)}
              className="heat-cell"
            >
              <title>{c.detail}</title>
              <rect x={cx} y={cy} width={size} height={size} rx={8} fill={zColor(c.z, dark)} />
              <text x={cx + size / 2} y={cy + size / 2} textAnchor="middle" dominantBaseline="central" fontSize="15" fontWeight="600" fill={zTextColor(c.z, dark)}>
                {String(c.n).padStart(2, '0')}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="heat-detail" aria-live="polite">
        {active ? active.detail : 'Passe o mouse ou foque uma dezena para ver os detalhes.'}
      </p>
      <HeatLegend dark={dark} />
    </div>
  );
}

export function HeatLegend({ dark }: { dark: boolean }) {
  const steps = [-3, -2, -1, 0, 1, 2, 3];
  return (
    <div className="heat-legend" aria-label="Escala de z-score">
      <span>abaixo do esperado</span>
      {steps.map((z) => (
        <span key={z} className="heat-step" style={{ background: zColor(clampZ(z), dark), color: zTextColor(z, dark) }}>
          {z > 0 ? '+' + z : z}
        </span>
      ))}
      <span>acima do esperado</span>
    </div>
  );
}

// ---------- Pontos com IC: valor × baseline ----------
export interface PointRow {
  label: string;
  value: number | null;
  low: number | null;
  high: number | null;
  baseline: number | null;
  baseLow: number | null;
  baseHigh: number | null;
}

export function PointsCI({ rows, title, fmt = defaultFmt }: { rows: PointRow[]; title: string; fmt?: Fmt }) {
  const rowH = 38;
  const m: Margin = { l: 170, r: 16, t: 10, b: 26 };
  const W = 640;
  const H = m.t + m.b + rows.length * rowH;
  const nums = rows.flatMap((r) => [r.value, r.low, r.high, r.baseline, r.baseLow, r.baseHigh]).filter((v): v is number => v !== null && Number.isFinite(v));
  const [lo, hi] = extent(nums);
  const pad = (hi - lo) * 0.08 || 0.1;
  const x = linear(lo - pad, hi + pad, m.l, W - m.r);
  const ticks = niceTicks(lo - pad, hi + pad, 5);
  return (
    <div>
      <Frame title={title} width={W} height={H} desc="Valor do modelo e do baseline com intervalos de confiança">
        {ticks.map((t) => (
          <g key={t} className="axis">
            <line className="grid" x1={x(t)} x2={x(t)} y1={m.t} y2={H - m.b} />
            <text x={x(t)} y={H - 8} textAnchor="middle" fontSize="10">
              {fmt(t)}
            </text>
          </g>
        ))}
        {rows.map((r, i) => {
          const cy = m.t + i * rowH + rowH / 2;
          return (
            <g key={r.label}>
              <text className="axis" x={m.l - 8} y={cy} textAnchor="end" dominantBaseline="middle" fontSize="11">
                {r.label}
              </text>
              {r.baseline !== null && (
                <g className="pt-base">
                  {r.baseLow !== null && r.baseHigh !== null && <line x1={x(r.baseLow)} x2={x(r.baseHigh)} y1={cy + 7} y2={cy + 7} />}
                  <rect x={x(r.baseline) - 4} y={cy + 3} width={8} height={8} transform={'rotate(45 ' + x(r.baseline) + ' ' + (cy + 7) + ')'}>
                    <title>{'Baseline uniforme: ' + fmt(r.baseline)}</title>
                  </rect>
                </g>
              )}
              {r.value !== null && (
                <g className="pt-model">
                  {r.low !== null && r.high !== null && <line x1={x(r.low)} x2={x(r.high)} y1={cy - 7} y2={cy - 7} />}
                  <circle cx={x(r.value)} cy={cy - 7} r={5}>
                    <title>{'Modelo: ' + fmt(r.value) + (r.low !== null && r.high !== null ? ' (IC ' + fmt(r.low) + ' a ' + fmt(r.high) + ')' : '')}</title>
                  </circle>
                </g>
              )}
            </g>
          );
        })}
      </Frame>
      <Legend items={[{ cls: 'sw-model', name: 'Modelo (círculo, com IC)' }, { cls: 'sw-base', name: 'Baseline uniforme (losango, com IC)' }]} />
    </div>
  );
}

// ---------- Trajetórias percentis ----------
export function PercentileLines({
  x,
  series,
  title,
  fmt = defaultFmt,
  xLabel,
  costCurve,
}: {
  x: number[];
  series: Record<string, number[]>;
  title: string;
  fmt?: Fmt;
  xLabel?: string;
  costCurve?: number[];
}) {
  const W = 700;
  const H = 300;
  const m: Margin = { l: 64, r: 14, t: 14, b: 30 };
  const keys = ['5', '25', '50', '75', '95'].filter((k) => series[k] && (series[k] as number[]).length === x.length);
  const all = keys.flatMap((k) => series[k] as number[]).concat(costCurve ?? []);
  if (x.length < 2 || keys.length === 0) return <p className="muted">Sem trajetórias para exibir.</p>;
  const [lo, hi] = extent(all);
  const pad = (hi - lo) * 0.06 || 1;
  const sx = linear(x[0] as number, x[x.length - 1] as number, m.l, W - m.r);
  const sy = linear(lo - pad, hi + pad, H - m.b, m.t);
  const path = (vals: number[]) => vals.map((v, i) => (i === 0 ? 'M' : 'L') + sx(x[i] as number).toFixed(1) + ' ' + sy(v).toFixed(1)).join(' ');
  const area = (a: number[], b: number[]) =>
    path(a) + ' ' + b.map((_, i) => 'L' + sx(x[b.length - 1 - i] as number).toFixed(1) + ' ' + sy(b[b.length - 1 - i] as number).toFixed(1)).join(' ') + ' Z';
  const yt = niceTicks(lo - pad, hi + pad, 5);
  const xt = niceTicks(x[0] as number, x[x.length - 1] as number, 6);
  const has = (k: string) => keys.includes(k);
  return (
    <div>
      <Frame title={title} width={W} height={H} desc="Percentis 5, 25, 50, 75 e 95 ao longo dos concursos">
        <YAxis ticks={yt} y={sy} m={m} w={W} fmt={fmt} />
        {has('5') && has('95') && <path className="area-outer" d={area(series['5'] as number[], series['95'] as number[])} />}
        {has('25') && has('75') && <path className="area-inner" d={area(series['25'] as number[], series['75'] as number[])} />}
        {has('50') && <path className="curve" d={path(series['50'] as number[])} fill="none" />}
        {costCurve && costCurve.length === x.length && <path className="curve-cost" d={path(costCurve)} fill="none" />}
        {lo - pad < 0 && hi + pad > 0 && <line className="zero" x1={m.l} x2={W - m.r} y1={sy(0)} y2={sy(0)} />}
        <g className="axis">
          {xt.map((t) => (
            <text key={t} x={sx(t)} y={H - 12} textAnchor="middle" fontSize="10">
              {fmt(t)}
            </text>
          ))}
          {xLabel && (
            <text x={W - m.r} y={H - 1} textAnchor="end" fontSize="10">
              {xLabel}
            </text>
          )}
        </g>
      </Frame>
      <Legend
        items={[
          { cls: 'sw-outer', name: 'Faixa p5–p95' },
          { cls: 'sw-inner', name: 'Faixa p25–p75' },
          { cls: 'sw-curve', name: 'Mediana (p50)' },
          ...(costCurve ? [{ cls: 'sw-cost', name: 'Custo acumulado' }] : []),
        ]}
      />
    </div>
  );
}
