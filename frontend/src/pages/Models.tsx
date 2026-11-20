import { useState, type FormEvent } from 'react';
import { api, ApiError } from '../api/client';
import type { BacktestRequest, ExperimentDetail, ExperimentResult, Lottery, ModelInfo } from '../api/types';
import { LOTTERIES } from '../api/types';
import { useApi, clearCache } from '../lib/useApi';
import { AsyncView, Card, Empty, Field, Notice, PageHeader, Skeleton, Stat, Table, Tag } from '../components/ui';
import { ExperimentList, ProgressBar, VerdictTag, isFinished, useExperiment } from '../components/experiment';
import { PointsCI, type PointRow } from '../charts/charts';
import { fmtDateTime, fmtNum, fmtPValue, fmtInt } from '../lib/format';
import { CONCLUSION_LABELS, LOTTERY_NAMES, METRIC_LABELS, STATUS_LABELS } from '../lib/names';
import { href } from '../lib/router';

const FAMILY: Record<ModelInfo['family'], string> = { baseline: 'Baseline', frequency: 'Frequência', delay: 'Atraso', ml: 'Aprendizado de máquina' };

function ModelList({ items }: { items: ModelInfo[] }) {
  if (items.length === 0) return <Empty>Nenhum modelo registrado.</Empty>;
  return (
    <div className="grid grid-3">
      {items.map((m) => (
        <div key={m.name} className="mini-card">
          <strong>{m.label}</strong> <code className="small">{m.name}</code>
          <div>
            <Tag>{FAMILY[m.family]}</Tag> {m.experimental && <Tag tone="warn">experimental</Tag>} {m.probabilistic && <Tag tone="info">probabilístico</Tag>}
          </div>
          <p className="small muted">{m.description}</p>
        </div>
      ))}
    </div>
  );
}

function intIn(v: string, lo: number, hi: number): number | null {
  const n = Number(v);
  return Number.isInteger(n) && n >= lo && n <= hi ? n : null;
}

function BacktestForm({ models }: { models: ModelInfo[] | null }) {
  const [lottery, setLottery] = useState<Lottery>('megasena');
  const [selected, setSelected] = useState<string[] | null>(null);
  const [testContests, setTestContests] = useState('500');
  const [tickets, setTickets] = useState('10');
  const [seeds, setSeeds] = useState('5');
  const [reps, setReps] = useState('500');
  const [refit, setRefit] = useState('50');
  const [seed, setSeed] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const chosen = selected ?? models?.filter((m) => m.default).map((m) => m.name) ?? [];

  async function submit(e: FormEvent) {
    e.preventDefault();
    const tc = intIn(testContests, 50, 2000);
    const tk = intIn(tickets, 1, 50);
    const sd = intIn(seeds, 1, 10);
    const bp = intIn(reps, 50, 2000);
    const rf = intIn(refit, 10, 500);
    if (tc === null) return setErr('Concursos de teste: 50 a 2000.');
    if (tk === null) return setErr('Bilhetes por concurso: 1 a 50.');
    if (sd === null) return setErr('Sementes: 1 a 10.');
    if (bp === null) return setErr('Réplicas do baseline: 50 a 2000.');
    if (rf === null) return setErr('Reajuste a cada: 10 a 500.');
    if (seed !== '' && !Number.isInteger(Number(seed))) return setErr('A seed deve ser inteira.');
    const body: BacktestRequest = {
      kind: 'backtest',
      lottery,
      test_contests: tc,
      tickets_per_contest: tk,
      seeds: sd,
      baseline_replicates: bp,
      refit_every: rf,
      ...(chosen.length > 0 ? { models: chosen } : {}),
      ...(seed !== '' ? { seed: Number(seed) } : {}),
    };
    setErr(null);
    setBusy(true);
    try {
      const r = await api.createExperiment(body);
      clearCache('exp');
      window.location.hash = '/modelos/' + r.experiment_id;
    } catch (e2) {
      const ae = e2 as ApiError;
      setErr(ae.unavailable ? 'O serviço de experimentos ainda não está disponível no servidor.' : ae.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={submit} aria-label="Iniciar backtest">
      <Field label="Modalidade">
        <select value={lottery} onChange={(e) => setLottery(e.target.value as Lottery)}>
          {LOTTERIES.map((l) => (
            <option key={l} value={l}>
              {LOTTERY_NAMES[l]}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Concursos de teste (50–2000)">
        <input type="number" value={testContests} onChange={(e) => setTestContests(e.target.value)} />
      </Field>
      <Field label="Bilhetes por concurso (1–50)">
        <input type="number" value={tickets} onChange={(e) => setTickets(e.target.value)} />
      </Field>
      <Field label="Sementes (1–10)">
        <input type="number" value={seeds} onChange={(e) => setSeeds(e.target.value)} />
      </Field>
      <Field label="Réplicas do baseline (50–2000)">
        <input type="number" value={reps} onChange={(e) => setReps(e.target.value)} />
      </Field>
      <Field label="Reajustar a cada N concursos (10–500)">
        <input type="number" value={refit} onChange={(e) => setRefit(e.target.value)} />
      </Field>
      <Field label="Seed (opcional)">
        <input type="number" value={seed} onChange={(e) => setSeed(e.target.value)} />
      </Field>
      <fieldset className="form-wide">
        <legend>Modelos</legend>
        {models === null ? (
          <p className="muted small">Lista de modelos indisponível; o servidor usará os modelos padrão.</p>
        ) : (
          models.map((m) => (
            <label key={m.name} className="check">
              <input type="checkbox" checked={chosen.includes(m.name)} onChange={(e) => setSelected(e.target.checked ? [...chosen, m.name] : chosen.filter((n) => n !== m.name))} /> {m.label}
            </label>
          ))
        )}
      </fieldset>
      <div className="form-actions">
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? 'Enviando…' : 'Iniciar backtest'}
        </button>
      </div>
      {err && (
        <p className="form-error form-wide" role="alert">
          {err}
        </p>
      )}
    </form>
  );
}

function byMetric(results: ExperimentResult[]): Map<string, ExperimentResult[]> {
  const m = new Map<string, ExperimentResult[]>();
  for (const r of results) m.set(r.metric_name, [...(m.get(r.metric_name) ?? []), r]);
  return m;
}

function halvesText(r: ExperimentResult): string | null {
  const h = r.payload && typeof r.payload === 'object' ? (r.payload as { halves?: { first?: { p_value?: number; value?: number }; second?: { p_value?: number; value?: number } } }).halves : undefined;
  if (!h || !h.first || !h.second) return null;
  return '1ª metade: valor ' + fmtNum(h.first.value ?? NaN, 4) + ', p ' + fmtPValue(h.first.p_value) + ' · 2ª metade: valor ' + fmtNum(h.second.value ?? NaN, 4) + ', p ' + fmtPValue(h.second.p_value);
}

export function BacktestResults({ d }: { d: ExperimentDetail }) {
  const e = d.experiment;
  const groups = byMetric(d.results);
  return (
    <>
      <Card title={'Backtest #' + e.id + ' — ' + (LOTTERY_NAMES[e.lottery_slug] ?? e.lottery_slug)}>
        <div className="stats">
          <Stat label="Status" value={STATUS_LABELS[e.status] ?? e.status} />
          <Stat label="Treino até o concurso" value={e.train_cutoff_contest !== null ? fmtInt(e.train_cutoff_contest) : '—'} />
          <Stat label="Teste" value={e.test_start_contest !== null ? fmtInt(e.test_start_contest) + ' – ' + fmtInt(e.test_end_contest) : '—'} hint="avaliação fora da amostra, em ordem cronológica" />
          <Stat label="Hipóteses testadas" value={e.n_hypotheses !== null ? fmtInt(e.n_hypotheses) : '—'} hint="base da correção de q-values" />
        </div>
        {!isFinished(e.status) && <ProgressBar progress={e.progress} status={e.status} />}
        {e.error && <p className="form-error">Erro: {e.error}</p>}
        <p className="small muted">
          seed {String(e.seed ?? '—')} · versão do código <code>{e.code_version ?? '—'}</code> · impressão digital dos dados <code>{e.data_fingerprint ? e.data_fingerprint.slice(0, 16) : '—'}</code> · criado em {fmtDateTime(e.created_at)}
        </p>
      </Card>
      {d.conclusion && (
        <Card title="Conclusão" className="conclusion">
          <p>
            <span className="verdict verdict-neu">{CONCLUSION_LABELS[d.conclusion.verdict] ?? d.conclusion.verdict}</span>
          </p>
          <p>{d.conclusion.summary}</p>
          <h3>Limitações</h3>
          <ul className="bullets">
            {d.conclusion.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </Card>
      )}
      {[...groups.entries()].map(([metric, rows]) => {
        const points: PointRow[] = rows.map((r) => ({ label: r.model_name, value: r.value, low: r.ci_low, high: r.ci_high, baseline: r.baseline_value, baseLow: r.baseline_ci_low, baseHigh: r.baseline_ci_high }));
        return (
          <Card key={metric} title={METRIC_LABELS[metric] ?? metric}>
            <PointsCI rows={points} title={'Modelo × baseline — ' + (METRIC_LABELS[metric] ?? metric)} fmt={(v) => fmtNum(v, 4)} />
            <Table caption={'Resultados de ' + metric}>
              <thead>
                <tr>
                  <th>Modelo</th>
                  <th className="r">Valor (IC)</th>
                  <th className="r">Baseline (IC)</th>
                  <th className="r">p</th>
                  <th className="r">q</th>
                  <th>Veredito</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.model_name}>
                    <td>{r.model_name}</td>
                    <td className="r num">
                      {fmtNum(r.value ?? NaN, 4)}
                      <div className="small muted">
                        {fmtNum(r.ci_low ?? NaN, 4)} a {fmtNum(r.ci_high ?? NaN, 4)}
                      </div>
                    </td>
                    <td className="r num">
                      {fmtNum(r.baseline_value ?? NaN, 4)}
                      <div className="small muted">
                        {fmtNum(r.baseline_ci_low ?? NaN, 4)} a {fmtNum(r.baseline_ci_high ?? NaN, 4)}
                      </div>
                    </td>
                    <td className="r num">{fmtPValue(r.p_value)}</td>
                    <td className="r num">{fmtPValue(r.q_value)}</td>
                    <td>
                      <VerdictTag verdict={r.verdict} />
                      {halvesText(r) && <div className="small muted">{halvesText(r)}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        );
      })}
      {d.results.length === 0 && isFinished(e.status) && <Empty>Este experimento não produziu resultados.</Empty>}
      <p className="small muted">{d.disclaimer}</p>
    </>
  );
}

function ExperimentView({ id }: { id: string }) {
  const { state, reload } = useExperiment(id);
  return (
    <>
      <p>
        <a href={href('/modelos')}>← Voltar para modelos e backtests</a>
      </p>
      <AsyncView state={state} onRetry={reload} what="O experimento" skeleton={<Card><Skeleton lines={6} /></Card>}>
        {(d) => (d.experiment.kind === 'montecarlo' ? <Notice>Este é um experimento Monte Carlo. Abra em <a href={href('/simulacoes/' + id)}>Simulações</a>.</Notice> : <BacktestResults d={d} />)}
      </AsyncView>
    </>
  );
}

export function ModelsPage({ experimentId }: { experimentId?: string; dark?: boolean }) {
  const models = useApi((s) => api.models(s), [], { key: 'models' });
  return (
    <>
      <PageHeader title="Modelos e backtests" subtitle="Compara estratégias com o baseline uniforme de mesmo custo, em ordem cronológica." />
      <Notice tone="warn" title="Leitura honesta:">
        resultados negativos e inconclusivos são tão importantes quanto positivos e aparecem com o mesmo destaque. Sorteios são independentes; o esperado é que nenhum modelo supere o baseline de forma replicada.
      </Notice>
      {experimentId ? (
        <ExperimentView id={experimentId} />
      ) : (
        <>
          <Card title="Modelos disponíveis">
            <AsyncView state={models.state} onRetry={models.reload} what="A lista de modelos">
              {(m) => <ModelList items={m.items} />}
            </AsyncView>
          </Card>
          <Card title="Iniciar backtest">
            <BacktestForm models={models.state.status === 'ok' ? models.state.data.items : null} />
          </Card>
          <Card title="Experimentos">
            <ExperimentList kind="backtest" base="/modelos" />
          </Card>
        </>
      )}
    </>
  );
}
