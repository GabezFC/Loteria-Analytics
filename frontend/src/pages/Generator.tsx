import { useState, type FormEvent } from 'react';
import { api, ApiError } from '../api/client';
import type { Lottery, Strategy, SuggestionDetail } from '../api/types';
import { LOTTERIES, STRATEGIES } from '../api/types';
import { useApi, clearCache } from '../lib/useApi';
import { AsyncView, Balls, Card, Empty, Field, Notice, PageHeader, Skeleton, Stat, Table, Tag } from '../components/ui';
import { fmtBRL, fmtDateTime, fmtFraction, fmtInt, fmtNum, fmtOneIn, fmtProb } from '../lib/format';
import { LOTTERY_NAMES, STATUS_LABELS, STRATEGY_LABELS } from '../lib/names';
import { href } from '../lib/router';

const STRATEGY_HELP: Record<Strategy, string> = {
  uniform_random: 'Sorteio uniforme: cada combinação tem exatamente a mesma chance. É o baseline.',
  diversity: 'Procura bilhetes com pouca sobreposição entre si (cobertura). Não muda a chance de cada bilhete.',
  frequency_weighted: 'Favorece dezenas historicamente mais frequentes. Sem vantagem comprovada.',
  delay_weighted: 'Favorece dezenas mais atrasadas. Sem vantagem comprovada (falácia do jogador).',
};

function Disclaimer() {
  return (
    <Notice tone="warn" title="Uso ilustrativo.">
      Sem vantagem preditiva comprovada. Qualquer bilhete tem a mesma chance de qualquer outro e o gerador não aumenta a chance de ganhar. A “pontuação descritiva” abaixo <strong>não é probabilidade</strong>. Este sistema não realiza apostas.
    </Notice>
  );
}

function Result({ d }: { d: SuggestionDetail }) {
  const s = d.set;
  return (
    <>
      <Card title={'Conjunto #' + s.id + ' — ' + (LOTTERY_NAMES[s.lottery_slug] ?? s.lottery_slug)}>
        <div className="stats">
          <Stat label="Estratégia" value={STRATEGY_LABELS[s.strategy] ?? s.strategy} />
          <Stat label="Bilhetes" value={fmtInt(s.ticket_count)} />
          <Stat label="Custo total" value={fmtBRL(s.total_cost)} hint={s.budget !== null ? 'orçamento ' + fmtBRL(s.budget) : undefined} />
          <Stat label="Base de dados" value={s.based_on_contest !== null ? 'até o concurso ' + fmtInt(s.based_on_contest) : '—'} />
        </div>
        {s.explanation && <p>{s.explanation}</p>}
        {s.jackpot_probability && (
          <p>
            <strong>Probabilidade matemática exata</strong> ({s.jackpot_probability.event}): {fmtFraction(s.jackpot_probability)} ≈ {fmtProb(s.jackpot_probability.probability)} — {fmtOneIn(null, s.jackpot_probability)}.
          </p>
        )}
        <p className="small muted">
          seed {String(s.seed ?? '—')} · criado em {fmtDateTime(s.created_at)} · vantagem preditiva validada: <strong>{d.predictive_advantage_validated ? 'sim' : 'não'}</strong> · uso ilustrativo: {d.illustrative_only ? 'sim' : 'não'}
        </p>
        {s.evidence ? (
          <p className="small">
            Evidência: experimento <a href={href('/modelos/' + s.evidence.experiment_id)}>#{s.evidence.experiment_id}</a>, modelo <code>{s.evidence.model_name}</code>, veredito <code>{s.evidence.verdict}</code>.
          </p>
        ) : (
          <p className="small muted">Evidência: nenhum experimento sustenta esta estratégia.</p>
        )}
      </Card>
      <Card title="Bilhetes">
        <Table caption="Bilhetes sugeridos">
          <thead>
            <tr>
              <th>#</th>
              <th>Dezenas</th>
              <th className="r" title="Pontuação descritiva de diversidade/modelo. NÃO é probabilidade.">
                Pontuação descritiva (NÃO é probabilidade)
              </th>
              <th className="r">Probabilidade exata do prêmio principal</th>
              <th className="r">Custo</th>
            </tr>
          </thead>
          <tbody>
            {d.tickets.map((t) => (
              <tr key={t.position}>
                <td className="num">{t.position}</td>
                <td>
                  <Balls numbers={t.numbers} />
                </td>
                <td className="r num">
                  {fmtNum(t.heuristic_score, 3)}
                  <div className="small muted">{t.score_interpretation}</div>
                </td>
                <td className="r num">
                  {fmtFraction(t.exact_jackpot_probability)}
                  <div className="small muted">{fmtOneIn(null, t.exact_jackpot_probability)}</div>
                </td>
                <td className="r num">{fmtBRL(t.cost)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
        <p className="small muted">{d.disclaimer}</p>
      </Card>
    </>
  );
}

function Tracker({ id }: { id: string }) {
  const { state, reload } = useApi((s) => api.suggestion(id, s), [id], {
    poll: (d: SuggestionDetail | null) => (d && (d.set.status === 'succeeded' || d.set.status === 'failed') ? null : 2000),
  });
  return (
    <AsyncView state={state} onRetry={reload} what="A sugestão" skeleton={<Card><Skeleton lines={5} /></Card>}>
      {(d) =>
        d.set.status === 'succeeded' ? (
          <Result d={d} />
        ) : d.set.status === 'failed' ? (
          <div className="state state-error" role="alert">
            <strong>A geração falhou.</strong> Tente novamente com outros parâmetros.
          </div>
        ) : (
          <Card title="Gerando…">
            <p role="status" aria-live="polite">
              Status: <Tag tone="info">{STATUS_LABELS[d.set.status] ?? d.set.status}</Tag> — acompanhando automaticamente.
            </p>
            <Skeleton lines={3} />
          </Card>
        )
      }
    </AsyncView>
  );
}

export function GeneratorPage({ suggestionId }: { suggestionId?: string }) {
  const [lottery, setLottery] = useState<Lottery>('megasena');
  const [strategy, setStrategy] = useState<Strategy>('uniform_random');
  const [mode, setMode] = useState<'tickets' | 'budget'>('tickets');
  const [amount, setAmount] = useState('5');
  const [seed, setSeed] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const list = useApi((s) => api.suggestions({ limit: 10 }, s), [suggestionId], { key: 'sug-list' });

  async function submit(e: FormEvent) {
    e.preventDefault();
    const a = Number(amount.replace(',', '.'));
    if (!Number.isFinite(a) || a <= 0) return setErr('Informe um valor positivo.');
    if (mode === 'tickets' && (!Number.isInteger(a) || a > 200)) return setErr('Bilhetes: inteiro de 1 a 200.');
    if (seed !== '' && !Number.isInteger(Number(seed))) return setErr('A seed deve ser inteira.');
    setErr(null);
    setBusy(true);
    try {
      const r = await api.createSuggestion({
        lottery,
        strategy,
        ...(mode === 'tickets' ? { tickets: a } : { budget: a }),
        ...(seed !== '' ? { seed: Number(seed) } : {}),
      });
      clearCache('sug-list');
      window.location.hash = '/gerador/' + r.suggestion_set_id;
    } catch (e2) {
      const ae = e2 as ApiError;
      setErr(ae.unavailable ? 'O gerador ainda não está disponível no servidor.' : ae.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Gerador experimental" subtitle="Gera bilhetes ilustrativos. Não é recomendação nem previsão." />
      <Disclaimer />
      <Card title="Novo conjunto">
        <form className="form" onSubmit={submit} aria-label="Gerar sugestões">
          <Field label="Modalidade">
            <select value={lottery} onChange={(e) => setLottery(e.target.value as Lottery)}>
              {LOTTERIES.map((l) => (
                <option key={l} value={l}>
                  {LOTTERY_NAMES[l]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Estratégia" hint={STRATEGY_HELP[strategy]}>
            <select value={strategy} onChange={(e) => setStrategy(e.target.value as Strategy)}>
              {STRATEGIES.map((s) => (
                <option key={s} value={s}>
                  {STRATEGY_LABELS[s]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Quantidade">
            <div className="inline">
              <select value={mode} onChange={(e) => setMode(e.target.value as 'tickets' | 'budget')} aria-label="Tipo de quantidade">
                <option value="tickets">Bilhetes (1–200)</option>
                <option value="budget">Orçamento (R$)</option>
              </select>
              <input type="text" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} aria-label="Valor" />
            </div>
          </Field>
          <Field label="Seed (opcional)" hint="Mesma seed + mesmos dados = mesmo resultado">
            <input type="number" inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value)} />
          </Field>
          <div className="form-actions">
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {busy ? 'Enviando…' : 'Gerar'}
            </button>
          </div>
        </form>
        {err && (
          <p className="form-error" role="alert">
            {err}
          </p>
        )}
      </Card>
      {suggestionId && <Tracker key={suggestionId} id={suggestionId} />}
      <Card title="Conjuntos recentes">
        <AsyncView state={list.state} onRetry={list.reload} what="A lista de sugestões">
          {(l) =>
            l.items.length === 0 ? (
              <Empty>Nenhum conjunto gerado ainda.</Empty>
            ) : (
              <ul className="list">
                {l.items.map((x) => (
                  <li key={x.id}>
                    <a href={href('/gerador/' + x.id)}>#{x.id}</a> · {LOTTERY_NAMES[x.lottery_slug] ?? x.lottery_slug} · {STRATEGY_LABELS[x.strategy] ?? x.strategy} · {x.ticket_count ?? '—'} bilhetes · <Tag>{STATUS_LABELS[x.status] ?? x.status}</Tag> <span className="muted small">{fmtDateTime(x.created_at)}</span>
                  </li>
                ))}
              </ul>
            )
          }
        </AsyncView>
      </Card>
    </>
  );
}
