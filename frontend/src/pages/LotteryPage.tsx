import { useState } from 'react';
import { api } from '../api/client';
import type { Combinations, GofDist, Inference, Lottery, Stats, WindowLabel } from '../api/types';
import { WINDOWS } from '../api/types';
import { useApi } from '../lib/useApi';
import { AsyncView, Card, Empty, ErrorBox, Field, Notice, PageHeader, Skeleton, Table, Tag } from '../components/ui';
import { BarBandChart, CategoryBars, Heatmap, Histogram } from '../charts/charts';
import { fmtInt, fmtNum, fmtPValue, fmtPct, pad2, fmtSigned } from '../lib/format';
import { LOTTERY_NAMES } from '../lib/names';
import { volanteDims } from '../lib/heatmap';
import { expectedBinCounts } from '../lib/stats';

const WINDOW_TEXT: Record<string, string> = { '30': 'Últimos 30', '100': 'Últimos 100', '300': 'Últimos 300', '1000': 'Últimos 1000', all: 'Todos' };

function DiscreteDist({ title, dist, kind }: { title: string; dist: GofDist; kind: string }) {
  const total = dist.observed.reduce((a, b) => a + b, 0);
  return (
    <div>
      <h3>{title}</h3>
      <CategoryBars
        title={title + ' — observado e esperado (hipergeométrica)'}
        labels={dist.values.map(String)}
        observed={dist.observed}
        expected={dist.expected}
        fmt={(v) => fmtNum(v, 0)}
      />
      <p className="small muted">
        Média observada {fmtNum(dist.mean ?? NaN, 3)} × esperada {fmtNum(dist.expected_mean ?? NaN, 3)} ({fmtInt(total)} concursos).
        {dist.gof && (
          <>
            {' '}
            Qui-quadrado de aderência ({kind}): χ² = {fmtNum(dist.gof.chi2, 2)}, gl = {dist.gof.df}, p = {fmtPValue(dist.gof.p_value)}.
          </>
        )}
      </p>
    </div>
  );
}

function FrequencySection({ stats, dark, lottery }: { stats: Stats; dark: boolean; lottery: Lottery }) {
  const N = stats.analysis_run.sample_size;
  const first = stats.numbers[0];
  const expectedRel = first ? first.expected_frequency / N : 0;
  const { rows, cols } = volanteDims(lottery);
  return (
    <>
      <Card title="Frequência por dezena" id="freq">
        <p className="muted small">
          Barras: frequência relativa observada; hastes: intervalo de confiança binomial; linha tracejada: expectativa k/N = {fmtPct(expectedRel, 2)}. A maioria das hastes cruza a linha — diferenças são esperadas por acaso.
        </p>
        <BarBandChart
          title={'Frequência relativa por dezena — ' + LOTTERY_NAMES[lottery]}
          data={stats.numbers.map((x) => ({
            label: pad2(x.number),
            value: x.relative_frequency,
            low: x.ci_low,
            high: x.ci_high,
            tip: 'Dezena ' + pad2(x.number) + ': ' + fmtPct(x.relative_frequency, 2) + ' (' + fmtInt(x.frequency) + ' vezes; IC ' + fmtPct(x.ci_low, 2) + '–' + fmtPct(x.ci_high, 2) + '; z = ' + fmtSigned(x.z_score) + ')',
          }))}
          expected={expectedRel}
          fmt={(v) => fmtPct(v, 1)}
        />
      </Card>
      <Card title="Mapa do volante (z-score)" id="heat">
        <p className="muted small">Cor = desvio da frequência esperada (z, binomial), saturado em ±3. É descrição do passado, não indício de “dezena quente”.</p>
        <Heatmap
          label={'Volante de ' + LOTTERY_NAMES[lottery] + ' colorido por z-score'}
          rows={rows}
          cols={cols}
          dark={dark}
          cells={stats.numbers.map((x) => ({
            n: x.number,
            z: x.z_score,
            detail:
              'Dezena ' + pad2(x.number) + ' — ' + fmtInt(x.frequency) + ' ocorrências (esperado ' + fmtNum(x.expected_frequency, 1) + '), z = ' + fmtSigned(x.z_score) + ', atraso atual ' + fmtInt(x.current_delay),
          }))}
        />
      </Card>
    </>
  );
}

function DelaysSection({ stats }: { stats: Stats }) {
  const [all, setAll] = useState(false);
  const sorted = [...stats.numbers].sort((a, b) => b.current_delay - a.current_delay);
  const shown = all ? sorted : sorted.slice(0, 12);
  return (
    <Card title="Atrasos" id="delays">
      <p className="muted small">
        Atraso atual = concursos desde a última aparição. Comparado ao máximo histórico e à média de intervalo. Um número “atrasado” <strong>não</strong> tem mais chance de sair (sorteios são independentes).
      </p>
      <Table caption="Atrasos por dezena">
        <thead>
          <tr>
            <th>Dezena</th>
            <th className="r">Atual</th>
            <th className="r">Máximo</th>
            <th className="r">Média do intervalo</th>
            <th className="r">Frequência</th>
            <th className="r">z</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((x) => (
            <tr key={x.number}>
              <td className="num">{pad2(x.number)}</td>
              <td className="r num">{fmtInt(x.current_delay)}</td>
              <td className="r num">{fmtInt(x.max_delay)}</td>
              <td className="r num">{x.mean_gap === null ? '—' : fmtNum(x.mean_gap, 1)}</td>
              <td className="r num">{fmtInt(x.frequency)}</td>
              <td className="r num">{fmtSigned(x.z_score)}</td>
            </tr>
          ))}
        </tbody>
      </Table>
      <button type="button" className="btn btn-ghost" onClick={() => setAll((v) => !v)}>
        {all ? 'Mostrar só os 12 maiores atrasos' : 'Mostrar todas as ' + sorted.length + ' dezenas'}
      </button>
    </Card>
  );
}

function DistributionsSection({ stats, lottery }: { stats: Stats; lottery: Lottery }) {
  const d = stats.distributions;
  const N = stats.analysis_run.sample_size;
  const s = d.sum;
  const exp = expectedBinCounts(s.histogram.edges, N, s.expected_mean, s.expected_variance);
  const g = d.groups_of_ten;
  return (
    <>
      <Card title="Soma das dezenas" id="sum">
        <Histogram
          title={'Histograma da soma das dezenas — ' + LOTTERY_NAMES[lottery]}
          edges={s.histogram.edges}
          counts={s.histogram.counts}
          expectedCounts={exp}
          markers={[
            { value: s.mean, label: 'média ' + fmtNum(s.mean, 1) },
            { value: s.expected_mean, label: 'esperada ' + fmtNum(s.expected_mean, 1) },
          ]}
          fmt={(v) => fmtNum(v, 0)}
        />
        <p className="small muted">
          Média {fmtNum(s.mean, 2)} (esperada {fmtNum(s.expected_mean, 2)}), mediana {fmtNum(s.median, 1)}, desvio-padrão {fmtNum(s.std, 2)} (esperado {fmtNum(Math.sqrt(s.expected_variance), 2)}), intervalo {fmtInt(s.min)}–{fmtInt(s.max)}. A curva é a aproximação normal da soma sob sorteio uniforme.
        </p>
      </Card>
      <Card title="Paridade, baixos/altos e repetidas" id="parity">
        <div className="grid grid-2">
          <DiscreteDist title="Pares por concurso" dist={d.parity.evens_per_draw} kind="paridade" />
          <DiscreteDist title="Baixas por concurso" dist={d.low_high.low_per_draw} kind="baixas/altas" />
          <DiscreteDist title="Repetidas do concurso anterior" dist={d.repeated_from_previous} kind="repetidas" />
          <div>
            <h3>Consecutivas</h3>
            <CategoryBars
              title="Pares de dezenas consecutivas por concurso (observado)"
              labels={d.consecutive.pairs_per_draw_distribution.values.map(String)}
              observed={d.consecutive.pairs_per_draw_distribution.observed}
              fmt={(v) => fmtNum(v, 0)}
            />
            <p className="small muted">
              Média observada {fmtNum(d.consecutive.mean, 3)} × esperada {fmtNum(d.consecutive.expected_mean, 3)} pares por concurso.
            </p>
          </div>
        </div>
        {(d.parity.note || d.low_high.note) && <p className="small muted">{[d.parity.note, d.low_high.note].filter(Boolean).join(' · ')}</p>}
      </Card>
      <Card title="Linhas, colunas e dezenas do volante" id="volante">
        <div className="grid grid-2">
          <div>
            <h3>Dezenas por linha (média por concurso)</h3>
            <BarBandChart title="Média de dezenas por linha do volante" data={d.volante.row_mean_per_draw.map((v, i) => ({ label: 'L' + (i + 1), value: v }))} expected={d.volante.expected_row_mean} fmt={(v) => fmtNum(v, 3)} />
          </div>
          <div>
            <h3>Dezenas por coluna (média por concurso)</h3>
            <BarBandChart title="Média de dezenas por coluna do volante" data={d.volante.column_mean_per_draw.map((v, i) => ({ label: 'C' + (i + 1), value: v }))} expected={d.volante.expected_column_mean} fmt={(v) => fmtNum(v, 3)} />
          </div>
        </div>
        {g.length > 0 && (
          <>
            <h3>Grupos de dez</h3>
            <CategoryBars
              title="Média de dezenas por grupo de dez, observada e esperada"
              labels={g.map((x) => x.range[0] + '–' + x.range[1])}
              observed={g.map((x) => x.mean_per_draw)}
              expected={g.map((x) => x.expected_mean_per_draw)}
              fmt={(v) => fmtNum(v, 3)}
            />
          </>
        )}
      </Card>
    </>
  );
}

function CombosSection({ lottery, window, available }: { lottery: Lottery; window: WindowLabel; available: boolean }) {
  const [size, setSize] = useState(2);
  const [order, setOrder] = useState<'over' | 'under'>('over');
  const { state, reload } = useApi<Combinations>((s) => api.combinations(lottery, window, size, order, 30, s), [lottery, window, size, order], {
    key: 'combos:' + [lottery, window, size, order].join(':'),
    enabled: available,
  });
  return (
    <Card title="Pares, trios e quartetos" id="combos">
      <div className="toolbar">
        <Field label="Tamanho">
          <select value={size} onChange={(e) => setSize(Number(e.target.value))}>
            <option value={2}>Pares</option>
            <option value={3}>Trios</option>
            <option value={4}>Quartetos</option>
          </select>
        </Field>
        <Field label="Ordenar por">
          <select value={order} onChange={(e) => setOrder(e.target.value as 'over' | 'under')}>
            <option value="over">Mais frequentes que o esperado (over)</option>
            <option value="under">Menos frequentes que o esperado (under)</option>
          </select>
        </Field>
      </div>
      {!available ? (
        <Empty>Combinações exigem janelas com pelo menos 300 concursos. Escolha 300, 1000 ou Todos.</Empty>
      ) : (
        <AsyncView state={state} onRetry={reload} what="A análise de combinações">
          {(c) => {
            const m = c.meta.sizes[String(size)];
            return (
              <>
                <Notice tone="warn" title="Atenção a falsos positivos:">
                  {m ? (
                    <>
                      foram testadas {fmtInt(m.tested)} de {fmtInt(m.possible)} combinações; com limiar de 5% são esperados ≈ <strong>{fmtInt(m.expected_false_positives_at_05)}</strong> falsos positivos por acaso. Significativas após correção (q &lt; 0,05): <strong>{fmtInt(m.significant_q05)}</strong>.{' '}
                    </>
                  ) : (
                    'a contagem de falsos positivos esperados não veio nesta resposta. '
                  )}
                  {c.note}
                </Notice>
                {c.items.length === 0 ? (
                  <Empty>Sem combinações nesta consulta.</Empty>
                ) : (
                  <Table caption="Combinações de dezenas">
                    <thead>
                      <tr>
                        <th>Dezenas</th>
                        <th className="r">Observado</th>
                        <th className="r">Esperado</th>
                        <th className="r">Lift</th>
                        <th className="r">z</th>
                        <th className="r">p</th>
                        <th className="r">q (FDR)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {c.items.map((it) => (
                        <tr key={it.numbers.join('-')}>
                          <td className="num">{it.numbers.map(pad2).join(' – ')}</td>
                          <td className="r num">{fmtInt(it.observed)}</td>
                          <td className="r num">{fmtNum(it.expected, 2)}</td>
                          <td className="r num">{fmtNum(it.lift, 2)}</td>
                          <td className="r num">{fmtSigned(it.z_score)}</td>
                          <td className="r num">{fmtPValue(it.p_value)}</td>
                          <td className="r num">{fmtPValue(it.q_value)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                )}
                <p className="small muted">{c.disclaimer}</p>
              </>
            );
          }}
        </AsyncView>
      )}
    </Card>
  );
}

function TestRow({ name, h0, stat, p }: { name: string; h0: string; stat: string; p: number | null | undefined }) {
  return (
    <tr>
      <th scope="row">{name}</th>
      <td>
        <em>H₀:</em> {h0}
      </td>
      <td className="num">{stat}</td>
      <td className="r num">{fmtPValue(p)}</td>
    </tr>
  );
}

function InferenceSection({ lottery, window, available }: { lottery: Lottery; window: WindowLabel; available: boolean }) {
  const { state, reload } = useApi((s) => api.inference(lottery, window, s), [lottery, window], { key: 'inf:' + lottery + ':' + window, enabled: available });
  return (
    <Card title="Testes de inferência" id="inference">
      <Notice tone="info" title="Como ler:">
        cada teste parte de uma hipótese nula (sorteio uniforme e independente). Um p-value baixo indica que os dados passados seriam raros sob essa hipótese; <strong>rejeitar H₀ não significa que o próximo sorteio seja previsível</strong>. Com muitos testes, alguns p-values baixos aparecem por acaso.
      </Notice>
      {!available ? (
        <Empty>Testes de inferência exigem pelo menos 100 concursos na janela.</Empty>
      ) : (
        <AsyncView state={state} onRetry={reload} what="Os testes de inferência">
          {(r) => (r.inference ? <InferenceTable inf={r.inference} /> : <Empty>Inferência ainda não calculada para esta janela.</Empty>)}
        </AsyncView>
      )}
    </Card>
  );
}

function InferenceTable({ inf }: { inf: Inference }) {
  const ac = inf.autocorrelation_lag1;
  const top = [...ac.per_number].sort((a, b) => a.p_value - b.p_value).slice(0, 5);
  return (
    <>
      <Table caption="Testes estatísticos">
        <thead>
          <tr>
            <th>Teste</th>
            <th>Hipótese nula</th>
            <th>Estatística</th>
            <th className="r">p-value</th>
          </tr>
        </thead>
        <tbody>
          <TestRow
            name="Qui-quadrado (uniformidade)"
            h0={inf.chi_square_uniformity.null_hypothesis}
            stat={'χ² = ' + fmtNum(inf.chi_square_uniformity.statistic, 2) + ' (gl ' + inf.chi_square_uniformity.df + ')'}
            p={inf.chi_square_uniformity.p_value_monte_carlo ?? inf.chi_square_uniformity.p_value_asymptotic}
          />
          <TestRow
            name="Entropia"
            h0={inf.entropy.null_hypothesis ?? 'frequências compatíveis com sorteio uniforme'}
            stat={fmtNum(inf.entropy.bits, 4) + ' bits (máx. ' + fmtNum(inf.entropy.max_bits, 4) + ')'}
            p={inf.entropy.p_value_lower_tail}
          />
          <TestRow
            name="Autocorrelação (lag 1, máx. |z|)"
            h0={ac.null_hypothesis}
            stat={'máx. |z| = ' + fmtNum(ac.max_abs_z, 2) + ' em ' + fmtInt(ac.tests) + ' testes'}
            p={ac.p_value_permutation_max_abs_z}
          />
          <TestRow
            name="Ljung-Box (soma)"
            h0={inf.sum_ljung_box.null_hypothesis}
            stat={'Q = ' + fmtNum(inf.sum_ljung_box.statistic, 2) + ' (' + inf.sum_ljung_box.lags + ' lags)'}
            p={inf.sum_ljung_box.p_value}
          />
          {inf.runs_test_sum && (
            <TestRow name="Testes de corridas (soma)" h0={inf.runs_test_sum.null_hypothesis} stat={fmtInt(inf.runs_test_sum.runs) + ' corridas (esp. ' + fmtNum(inf.runs_test_sum.expected_runs, 1) + '), z = ' + fmtSigned(inf.runs_test_sum.z)} p={inf.runs_test_sum.p_value} />
          )}
          {inf.window_stability && (
            <TestRow name="Estabilidade da janela" h0={inf.window_stability.null_hypothesis} stat={'JSD = ' + fmtNum(inf.window_stability.jsd_bits, 5) + ' bits'} p={inf.window_stability.p_value_permutation} />
          )}
          {inf.change_point_sum && (
            <TestRow name="Ponto de mudança (soma)" h0={inf.change_point_sum.null_hypothesis} stat={'candidato no índice ' + fmtInt(inf.change_point_sum.candidate_index) + ', estat. ' + fmtNum(inf.change_point_sum.statistic, 3)} p={inf.change_point_sum.p_value_permutation} />
          )}
        </tbody>
      </Table>
      <p className="small muted">
        Autocorrelação: {fmtInt(ac.significant_q05 ?? 0)} dezenas significativas após correção (q &lt; 0,05); {fmtNum(ac.expected_false_positives_at_05 ?? NaN, 1)} falsos positivos esperados a 5% sem correção. Menores p por dezena:{' '}
        {top.map((t) => pad2(t.number) + ' (p = ' + fmtPValue(t.p_value) + ', q = ' + fmtPValue(t.q_value) + ')').join('; ')}.
        {inf.change_point_sum?.note ? ' ' + inf.change_point_sum.note : ''}
        {inf.chi_square_uniformity.limitation ? ' ' + inf.chi_square_uniformity.limitation : ''}
      </p>
      {ac.per_number.length > 0 && (
        <details>
          <summary>Autocorrelação por dezena (z, p, q)</summary>
          <Table caption="Autocorrelação lag 1 por dezena">
            <thead>
              <tr>
                <th>Dezena</th>
                <th className="r">z</th>
                <th className="r">p</th>
                <th className="r">q</th>
              </tr>
            </thead>
            <tbody>
              {ac.per_number.map((r) => (
                <tr key={r.number}>
                  <td className="num">{pad2(r.number)}</td>
                  <td className="r num">{fmtSigned(r.z)}</td>
                  <td className="r num">{fmtPValue(r.p_value)}</td>
                  <td className="r num">{fmtPValue(r.q_value)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </details>
      )}
    </>
  );
}

export function LotteryPage({ lottery, dark }: { lottery: Lottery; dark: boolean }) {
  const [window, setWindow] = useState<WindowLabel>('all');
  const wins = useApi((s) => api.statsWindows(lottery, s), [lottery], { key: 'windows:' + lottery });
  const stats = useApi((s) => api.stats(lottery, window, s), [lottery, window], { key: 'stats:' + lottery + ':' + window });
  const available = wins.state.status === 'ok' ? wins.state.data.items.map((i) => i.window_label) : [...WINDOWS];
  const sample = stats.state.status === 'ok' ? stats.state.data.analysis_run.sample_size : null;
  const comboAvail = stats.state.status === 'ok' ? stats.state.data.meta.combinations_available : false;
  const infAvail = stats.state.status === 'ok' ? stats.state.data.meta.inference_available : false;

  return (
    <>
      <PageHeader title={LOTTERY_NAMES[lottery]} subtitle="Estatísticas descritivas e testes sobre resultados oficiais. Medidas do passado; não são previsões.">
        <Field label="Janela de concursos">
          <select value={window} onChange={(e) => setWindow(e.target.value as WindowLabel)} aria-label="Janela de concursos">
            {WINDOWS.map((w) => (
              <option key={w} value={w} disabled={!available.includes(w)}>
                {WINDOW_TEXT[w]}
                {!available.includes(w) ? ' (indisponível)' : ''}
              </option>
            ))}
          </select>
        </Field>
      </PageHeader>
      <Notice tone="info">
        Frequência histórica não altera a chance do próximo concurso: sorteios são independentes e uniformes. Chance matemática, frequência observada e testes estatísticos são medidas distintas.
      </Notice>
      <AsyncView state={stats.state} onRetry={stats.reload} what="A análise estatística desta janela" skeleton={<Card><Skeleton lines={8} height={20} /></Card>}>
        {(s) => (
          <>
            <FrequencySection stats={s} dark={dark} lottery={lottery} />
            <DelaysSection stats={s} />
            <DistributionsSection stats={s} lottery={lottery} />
          </>
        )}
      </AsyncView>
      {stats.state.status !== 'error' && (
        <>
          <CombosSection lottery={lottery} window={window} available={comboAvail || sample === null} />
          <InferenceSection lottery={lottery} window={window} available={infAvail || sample === null} />
        </>
      )}
      {stats.state.status === 'ok' && <TechFooter stats={stats.state.data} />}
      {stats.state.status === 'error' && <ErrorBox error={stats.state.error} what="A análise" />}
    </>
  );
}

function TechFooter({ stats }: { stats: Stats }) {
  const r = stats.analysis_run;
  return (
    <footer className="tech-footer" aria-label="Rodapé técnico">
      <strong>Rodapé técnico</strong> · amostra: {fmtInt(r.sample_size)} concursos (#{fmtInt(r.window_start_contest)}–#{fmtInt(r.window_end_contest)}) · janela: {r.window_label} · versão do código: <code>{r.code_version}</code> · seed: <code>{String(r.seed ?? stats.meta.seed ?? '—')}</code> · stats: <code>{stats.meta.stats_version}</code> · cálculo em {new Date(r.completed_at).toLocaleString('pt-BR')}
      <br />
      <span className="muted">{stats.disclaimer ?? stats.meta.disclaimer}</span> <Tag>Tags e cores não indicam previsão</Tag>
    </footer>
  );
}
