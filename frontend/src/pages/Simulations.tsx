import { useState, type FormEvent } from 'react';
import { api, ApiError } from '../api/client';
import type { ExperimentDetail, ExperimentResult, Lottery } from '../api/types';
import { LOTTERIES } from '../api/types';
import { clearCache } from '../lib/useApi';
import { AsyncView, Card, Empty, Field, Notice, PageHeader, Skeleton, Stat } from '../components/ui';
import { ExperimentList, ProgressBar, isFinished, useExperiment } from '../components/experiment';
import { CategoryBars, Histogram, PercentileLines } from '../charts/charts';
import { fmtBRL, fmtInt, fmtNum, fmtPValue, fmtPct, fmtProb, fmtDateTime } from '../lib/format';
import { LOTTERY_NAMES, STATUS_LABELS } from '../lib/names';
import { href } from '../lib/router';

function isNumArr(v: unknown): v is number[] {
  return Array.isArray(v) && v.every((x) => typeof x === 'number');
}
function rec(v: unknown): Record<string, unknown> | null {
  return typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}
function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function find(results: ExperimentResult[], metric: string): ExperimentResult | undefined {
  return results.find((r) => r.metric_name === metric);
}

function intIn(v: string, lo: number, hi: number): number | null {
  const n = Number(v);
  return Number.isInteger(n) && n >= lo && n <= hi ? n : null;
}

function SimForm() {
  const [lottery, setLottery] = useState<Lottery>('megasena');
  const [tickets, setTickets] = useState('10');
  const [contests, setContests] = useState('500');
  const [reps, setReps] = useState('200');
  const [seed, setSeed] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const tk = intIn(tickets, 1, 100);
    const ct = intIn(contests, 1, 5000);
    const rp = intIn(reps, 10, 2000);
    if (tk === null) return setErr('Bilhetes por concurso: 1 a 100.');
    if (ct === null) return setErr('Concursos: 1 a 5000.');
    if (rp === null) return setErr('Réplicas: 10 a 2000.');
    if (seed !== '' && !Number.isInteger(Number(seed))) return setErr('A seed deve ser inteira.');
    setErr(null);
    setBusy(true);
    try {
      const r = await api.createExperiment({ kind: 'montecarlo', lottery, tickets_per_contest: tk, contests: ct, replicates: rp, ...(seed !== '' ? { seed: Number(seed) } : {}) });
      clearCache('exp');
      window.location.hash = '/simulacoes/' + r.experiment_id;
    } catch (e2) {
      const ae = e2 as ApiError;
      setErr(ae.unavailable ? 'O serviço de simulações ainda não está disponível no servidor.' : ae.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form className="form" onSubmit={submit} aria-label="Iniciar simulação Monte Carlo">
        <Field label="Modalidade">
          <select value={lottery} onChange={(e) => setLottery(e.target.value as Lottery)}>
            {LOTTERIES.map((l) => (
              <option key={l} value={l}>
                {LOTTERY_NAMES[l]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Bilhetes por concurso (1–100)">
          <input type="number" value={tickets} onChange={(e) => setTickets(e.target.value)} />
        </Field>
        <Field label="Concursos (1–5000)">
          <input type="number" value={contests} onChange={(e) => setContests(e.target.value)} />
        </Field>
        <Field label="Réplicas (10–2000)">
          <input type="number" value={reps} onChange={(e) => setReps(e.target.value)} />
        </Field>
        <Field label="Seed (opcional)">
          <input type="number" value={seed} onChange={(e) => setSeed(e.target.value)} />
        </Field>
        <div className="form-actions">
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? 'Enviando…' : 'Simular'}
          </button>
        </div>
      </form>
      {err && (
        <p className="form-error" role="alert">
          {err}
        </p>
      )}
    </>
  );
}

export function SimulationResults({ d }: { d: ExperimentDetail }) {
  const e = d.experiment;
  const hits = rec(find(d.results, 'hits_distribution')?.payload);
  const paths = rec(find(d.results, 'net_result_paths')?.payload);
  const fin = rec(find(d.results, 'final_net_distribution')?.payload);
  const jack = find(d.results, 'jackpot_probability');
  const cfg = e.config;

  const hv = hits?.values;
  const hobs = hits?.observed_share;
  const hexp = hits?.expected_share;
  const pct = paths?.percentiles ? rec(paths.percentiles) : null;
  const series: Record<string, number[]> = {};
  if (pct) for (const [k, v] of Object.entries(pct)) if (isNumArr(v)) series[k] = v;
  const checkpoints = paths?.checkpoints;
  const cost = paths?.cost_curve;
  const edges = fin?.edges;
  const counts = fin?.counts;
  const share = num(fin?.share_positive);

  return (
    <>
      <Card title={'Simulação #' + e.id + ' — ' + (LOTTERY_NAMES[e.lottery_slug] ?? e.lottery_slug)}>
        <div className="stats">
          <Stat label="Status" value={STATUS_LABELS[e.status] ?? e.status} />
          <Stat label="Bilhetes por concurso" value={fmtInt(num(cfg.tickets_per_contest))} />
          <Stat label="Concursos" value={fmtInt(num(cfg.contests))} />
          <Stat label="Réplicas" value={fmtInt(num(cfg.replicates))} />
        </div>
        {!isFinished(e.status) && <ProgressBar progress={e.progress} status={e.status} />}
        {e.error && <p className="form-error">Erro: {e.error}</p>}
        <p className="small muted">
          seed {String(e.seed ?? '—')} · código <code>{e.code_version ?? '—'}</code> · criado em {fmtDateTime(e.created_at)}
        </p>
      </Card>
      {share !== null && (
        <Card title="Resultado líquido final">
          <div className="stats">
            <Stat label="Réplicas com resultado positivo" value={fmtPct(share, 1)} hint="Parcela das simulações que terminou no lucro; não é uma recomendação." />
            <Stat label="Média" value={fmtBRL(num(fin?.mean))} />
            <Stat label="Mediana" value={fmtBRL(num(fin?.median))} />
            {jack && <Stat label="Prob. exata do prêmio principal no período" value={fmtProb(jack.value)} />}
          </div>
          {isNumArr(edges) && isNumArr(counts) && <Histogram title="Histograma do resultado líquido final (R$)" edges={edges} counts={counts} markers={[{ value: 0, label: 'R$ 0' }]} fmt={(v) => fmtNum(v, 0)} />}
        </Card>
      )}
      {isNumArr(hv) && isNumArr(hobs) && (
        <Card title="Distribuição de acertos: observada × teórica">
          <CategoryBars
            title="Parcela de bilhetes por número de acertos, simulada e teórica"
            labels={hv.map(String)}
            observed={isNumArr(hobs) ? hobs : []}
            expected={isNumArr(hexp) ? hexp : undefined}
            observedName="Simulada"
            expectedName="Teórica"
            fmt={(v) => fmtPct(v, 3)}
          />
          <p className="small muted">
            Aderência (qui-quadrado): p = {fmtPValue(num(hits?.gof_p_value))} · bilhetes simulados: {fmtInt(num(hits?.tickets_total))}. Um p alto indica que a simulação reproduz a distribuição teórica (validação do simulador).
          </p>
        </Card>
      )}
      {Object.keys(series).length > 0 && isNumArr(checkpoints) && (
        <Card title="Trajetórias do resultado líquido acumulado">
          <PercentileLines x={checkpoints} series={series} costCurve={isNumArr(cost) ? cost : undefined} title="Percentis 5/25/50/75/95 do resultado líquido acumulado (R$) por concurso" xLabel="concurso simulado" fmt={(v) => fmtNum(v, 0)} />
          <p className="small muted">Custo acumulado é determinístico; o resultado líquido é prêmios menos custo. A dispersão cresce com o tempo e a mediana tende a ficar abaixo de zero.</p>
        </Card>
      )}
      {d.conclusion && (
        <Card title="Conclusão e limitações">
          <p>{d.conclusion.summary}</p>
          <ul className="bullets">
            {d.conclusion.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </Card>
      )}
      {d.results.length === 0 && isFinished(e.status) && <Empty>Esta simulação não produziu resultados.</Empty>}
      <p className="small muted">{d.disclaimer}</p>
    </>
  );
}

function SimView({ id }: { id: string }) {
  const { state, reload } = useExperiment(id);
  return (
    <>
      <p>
        <a href={href('/simulacoes')}>← Voltar para simulações</a>
      </p>
      <AsyncView state={state} onRetry={reload} what="A simulação" skeleton={<Card><Skeleton lines={6} /></Card>}>
        {(d) => (d.experiment.kind === 'backtest' ? <Notice>Este é um backtest. Abra em <a href={href('/modelos/' + id)}>Modelos e backtests</a>.</Notice> : <SimulationResults d={d} />)}
      </AsyncView>
    </>
  );
}

export function SimulationsPage({ experimentId }: { experimentId?: string }) {
  return (
    <>
      <PageHeader title="Simulações" subtitle="Monte Carlo: o que acontece, em média, ao jogar muitas vezes. Ferramenta educativa." />
      <Notice tone="warn" title="Sem recomendação de aumentar gastos.">
        Comprar mais bilhetes aumenta o custo na mesma proporção em que aumenta a chance; o valor esperado continua negativo. Não aposte valores que não pode perder. Este sistema não realiza apostas.
      </Notice>
      {experimentId ? (
        <SimView id={experimentId} />
      ) : (
        <>
          <Card title="Nova simulação">
            <SimForm />
          </Card>
          <Card title="Simulações recentes">
            <ExperimentList kind="montecarlo" base="/simulacoes" />
          </Card>
        </>
      )}
    </>
  );
}
