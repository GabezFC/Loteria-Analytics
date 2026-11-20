import { useState, type FormEvent } from 'react';
import { api } from '../api/client';
import type { DrawDetail, Lottery } from '../api/types';
import { LOTTERIES } from '../api/types';
import { useApi } from '../lib/useApi';
import { AsyncView, Balls, Card, Empty, Field, PageHeader, Skeleton, Stat, Table } from '../components/ui';
import { fmtBRL, fmtDate, fmtInt } from '../lib/format';
import { LOTTERY_NAMES } from '../lib/names';

const PAGE = 20;

interface Filters {
  lottery: Lottery;
  contest: string;
  date_from: string;
  date_to: string;
  numbers: string;
}

function parseNumbers(s: string): string | null {
  const parts = s.split(/[\s,;]+/).filter(Boolean);
  if (parts.length === 0) return '';
  if (!parts.every((p) => /^\d{1,2}$/.test(p) && Number(p) >= 1 && Number(p) <= 99)) return null;
  return parts.map((p) => String(Number(p))).join(',');
}

function Detail({ lottery, contest, onClose }: { lottery: Lottery; contest: number; onClose: () => void }) {
  const { state, reload } = useApi((s) => api.draw(lottery, contest, s), [lottery, contest], { key: 'draw:' + lottery + ':' + contest });
  return (
    <Card
      title={LOTTERY_NAMES[lottery] + ' — concurso ' + contest}
      actions={
        <button type="button" className="btn btn-ghost" onClick={onClose}>
          Fechar
        </button>
      }
    >
      <AsyncView state={state} onRetry={reload} what="O detalhe do concurso" skeleton={<Skeleton lines={5} />}>
        {(d: DrawDetail) => (
          <>
            <p>
              <strong>{fmtDate(d.draw_date)}</strong> · <Balls numbers={d.numbers} />
            </p>
            <h3>Premiação</h3>
            {d.prizes.length === 0 ? (
              <Empty>Sem dados de premiação para este concurso.</Empty>
            ) : (
              <Table caption="Premiação por faixa">
                <thead>
                  <tr>
                    <th>Acertos</th>
                    <th className="r">Ganhadores</th>
                    <th className="r">Rateio</th>
                  </tr>
                </thead>
                <tbody>
                  {d.prizes.map((p) => (
                    <tr key={p.hits}>
                      <td className="num">{p.hits}</td>
                      <td className="r num">{fmtInt(p.winners)}</td>
                      <td className="r num">{fmtBRL(p.payout_amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
            {d.extra && (
              <>
                <h3>Dados financeiros</h3>
                <div className="stats">
                  <Stat label="Arrecadação total" value={fmtBRL(d.extra.total_collected)} />
                  <Stat label="Acumulado (prêmio principal)" value={fmtBRL(d.extra.accumulated_main)} />
                  <Stat label="Estimativa do próximo" value={fmtBRL(d.extra.next_estimate)} />
                  {d.extra.special_accumulated !== null && <Stat label="Acumulado especial" value={fmtBRL(d.extra.special_accumulated)} />}
                </div>
                {d.extra.observation && <p className="small">Observação: {d.extra.observation}</p>}
              </>
            )}
            <p className="small muted">
              fonte sha256 <code>{d.source_sha256.slice(0, 16)}…</code> · execução de coleta #{d.ingest_run_id}
            </p>
          </>
        )}
      </AsyncView>
    </Card>
  );
}

export function HistoryPage() {
  const [form, setForm] = useState<Filters>({ lottery: 'megasena', contest: '', date_from: '', date_to: '', numbers: '' });
  const [applied, setApplied] = useState<Filters>(form);
  const [offset, setOffset] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<{ lottery: Lottery; contest: number } | null>(null);

  const nums = parseNumbers(applied.numbers) ?? '';
  const query = {
    lottery: applied.lottery,
    limit: PAGE,
    offset,
    contest: applied.contest ? Number(applied.contest) : undefined,
    date_from: applied.date_from || undefined,
    date_to: applied.date_to || undefined,
    numbers: nums || undefined,
  };
  const list = useApi((s) => api.draws(query, s), [JSON.stringify(query)], { key: 'draws:' + JSON.stringify(query) });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (form.contest && (!/^\d+$/.test(form.contest) || Number(form.contest) < 1)) return setErr('Número do concurso inválido.');
    if (form.date_from && form.date_to && form.date_from > form.date_to) return setErr('A data inicial é posterior à final.');
    if (parseNumbers(form.numbers) === null) return setErr('Dezenas: use números de 1 a 99 separados por vírgula.');
    setErr(null);
    setOffset(0);
    setApplied(form);
    setOpen(null);
  }

  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <>
      <PageHeader title="Histórico" subtitle="Concursos oficiais validados. Clique em uma linha para ver premiação e dados financeiros." />
      <Card title="Filtros">
        <form className="form" onSubmit={submit} aria-label="Filtros do histórico">
          <Field label="Modalidade">
            <select value={form.lottery} onChange={(e) => set('lottery', e.target.value as Lottery)}>
              {LOTTERIES.map((l) => (
                <option key={l} value={l}>
                  {LOTTERY_NAMES[l]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Nº do concurso">
            <input type="number" inputMode="numeric" min={1} value={form.contest} onChange={(e) => set('contest', e.target.value)} />
          </Field>
          <Field label="Data inicial">
            <input type="date" value={form.date_from} onChange={(e) => set('date_from', e.target.value)} />
          </Field>
          <Field label="Data final">
            <input type="date" value={form.date_to} onChange={(e) => set('date_to', e.target.value)} />
          </Field>
          <Field label="Dezenas contidas" hint="Ex.: 5, 12, 33 (todas devem constar)">
            <input type="text" value={form.numbers} onChange={(e) => set('numbers', e.target.value)} />
          </Field>
          <div className="form-actions">
            <button className="btn btn-primary" type="submit">
              Filtrar
            </button>
          </div>
        </form>
        {err && (
          <p className="form-error" role="alert">
            {err}
          </p>
        )}
      </Card>
      {open && <Detail lottery={open.lottery} contest={open.contest} onClose={() => setOpen(null)} />}
      <Card title="Concursos">
        <AsyncView state={list.state} onRetry={list.reload} what="O histórico" skeleton={<Skeleton lines={8} height={20} />}>
          {(l) =>
            l.items.length === 0 ? (
              <Empty>Nenhum concurso encontrado com estes filtros.</Empty>
            ) : (
              <>
                <Table caption="Concursos">
                  <thead>
                    <tr>
                      <th>Concurso</th>
                      <th>Data</th>
                      <th>Dezenas</th>
                      <th>
                        <span className="sr-only">Ações</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {l.items.map((d) => (
                      <tr key={d.id} className="row-click" onClick={() => setOpen({ lottery: d.lottery_slug, contest: d.contest })}>
                        <td className="num">{fmtInt(d.contest)}</td>
                        <td className="num">{fmtDate(d.draw_date)}</td>
                        <td>
                          <Balls numbers={d.numbers} />
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn btn-ghost"
                            onClick={(ev) => {
                              ev.stopPropagation();
                              setOpen({ lottery: d.lottery_slug, contest: d.contest });
                            }}
                            aria-label={'Ver detalhes do concurso ' + d.contest}
                          >
                            Detalhes
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
                <nav className="pager" aria-label="Paginação">
                  <button type="button" className="btn btn-ghost" disabled={l.offset === 0} onClick={() => setOffset(Math.max(0, l.offset - PAGE))}>
                    ← Anterior
                  </button>
                  <span className="num">
                    {fmtInt(l.offset + 1)}–{fmtInt(l.offset + l.count)} de {fmtInt(l.total)}
                  </span>
                  <button type="button" className="btn btn-ghost" disabled={l.offset + l.count >= l.total} onClick={() => setOffset(l.offset + PAGE)}>
                    Próxima →
                  </button>
                </nav>
              </>
            )
          }
        </AsyncView>
      </Card>
    </>
  );
}
