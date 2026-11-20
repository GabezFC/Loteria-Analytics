import { useState } from 'react';
import { api, ApiError } from '../api/client';
import type { Lottery } from '../api/types';
import { LOTTERIES } from '../api/types';
import { useApi, clearCache } from '../lib/useApi';
import { AsyncView, Card, Empty, Field, Notice, PageHeader, Table, Tag } from '../components/ui';
import { fmtDate, fmtDateTime, fmtInt, pad2 } from '../lib/format';
import { LOTTERY_NAMES, STATUS_LABELS } from '../lib/names';

function Numbers({ n }: { n: number[] }) {
  return <span className="num">{n.map(pad2).join(' ')}</span>;
}

function TriggerCard() {
  const [lottery, setLottery] = useState<'' | Lottery>('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'ok' | 'warn' | 'err'; text: string } | null>(null);

  async function trigger() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.triggerIngestion(lottery === '' ? undefined : lottery);
      clearCache('jobs');
      setMsg({ tone: 'ok', text: 'Coleta enfileirada (job #' + r.job_id + ', status ' + r.status + ').' });
    } catch (e) {
      const ae = e as ApiError;
      if (ae.status === 409) setMsg({ tone: 'warn', text: 'Já existe uma coleta pendente; aguarde sua conclusão.' });
      else if (ae.status === 429) setMsg({ tone: 'warn', text: 'Limite de 6 coletas por minuto atingido. Tente de novo em instantes.' });
      else setMsg({ tone: 'err', text: ae.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Atualizar agora">
      <p className="muted">Dispara uma coleta manual dos resultados oficiais. Limite: 6 por minuto.</p>
      <div className="toolbar">
        <Field label="Modalidade">
          <select value={lottery} onChange={(e) => setLottery(e.target.value as '' | Lottery)}>
            <option value="">Todas</option>
            {LOTTERIES.map((l) => (
              <option key={l} value={l}>
                {LOTTERY_NAMES[l]}
              </option>
            ))}
          </select>
        </Field>
        <button type="button" className="btn btn-primary" onClick={trigger} disabled={busy}>
          {busy ? 'Enviando…' : 'Atualizar agora'}
        </button>
      </div>
      {msg && (
        <p className={msg.tone === 'err' ? 'form-error' : msg.tone === 'warn' ? 'form-warn' : 'form-ok'} role="status">
          {msg.text}
        </p>
      )}
    </Card>
  );
}

export function AdminPage() {
  const status = useApi((s) => api.ingestionStatus(s), [], { key: 'ingestion-status' });
  const runs = useApi((s) => api.ingestionRuns(15, s), [], { key: 'runs' });
  const div = useApi((s) => api.divergences(undefined, 30, s), [], { key: 'div' });
  const quar = useApi((s) => api.quarantine(30, s), [], { key: 'quar' });
  const jobs = useApi((s) => api.jobs({ limit: 20 }, s), [], { key: 'jobs-20', poll: 10000 });

  return (
    <>
      <PageHeader title="Administração" subtitle="Integridade dos dados, coletas e jobs." />
      <TriggerCard />
      <Card title="Integridade">
        <AsyncView state={status.state} onRetry={status.reload} what="O status de integridade">
          {(s) => (
            <Table caption="Integridade por modalidade">
              <thead>
                <tr>
                  <th>Modalidade</th>
                  <th className="r">Concursos</th>
                  <th className="r">Faixa</th>
                  <th className="r">Lacunas</th>
                  <th className="r">Divergências abertas</th>
                  <th className="r">Quarentena</th>
                  <th>Coletor</th>
                </tr>
              </thead>
              <tbody>
                {s.lotteries.map((l) => (
                  <tr key={l.lottery_slug}>
                    <td>{l.name}</td>
                    <td className="r num">{fmtInt(l.draw_count)}</td>
                    <td className="r num">
                      {fmtInt(l.first_contest)}–{fmtInt(l.last_contest)}
                    </td>
                    <td className="r">
                      <Tag tone={l.gap_count ? 'warn' : 'good'}>{fmtInt(l.gap_count)}</Tag>
                    </td>
                    <td className="r">
                      <Tag tone={l.open_divergences ? 'warn' : 'good'}>{fmtInt(l.open_divergences)}</Tag>
                    </td>
                    <td className="r">
                      <Tag tone={l.quarantined_rows ? 'warn' : 'good'}>{fmtInt(l.quarantined_rows)}</Tag>
                    </td>
                    <td className="small">
                      {l.collector ? (
                        <>
                          sucesso {fmtDateTime(l.collector.last_success_at)}
                          {l.collector.last_error ? ' · erro: ' + l.collector.last_error : ''}
                          <br />
                          próxima {fmtDateTime(l.collector.next_attempt_at)}
                        </>
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </AsyncView>
      </Card>
      <Card title="Divergências (antes × depois)">
        <AsyncView state={div.state} onRetry={div.reload} what="As divergências">
          {(d) =>
            d.items.length === 0 ? (
              <Empty>Nenhuma divergência registrada.</Empty>
            ) : (
              <Table caption="Divergências">
                <thead>
                  <tr>
                    <th>Concurso</th>
                    <th>Status</th>
                    <th>Antes</th>
                    <th>Depois</th>
                    <th>Detectada</th>
                    <th>Nota</th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((x) => (
                    <tr key={x.id}>
                      <td>
                        {LOTTERY_NAMES[x.lottery_slug] ?? x.lottery_slug} #{fmtInt(x.contest)}
                      </td>
                      <td>
                        <Tag tone={x.status === 'open' ? 'warn' : 'neutral'}>{x.status}</Tag>
                      </td>
                      <td>
                        {fmtDate(x.previous_value.draw_date)} <Numbers n={x.previous_value.numbers} />
                      </td>
                      <td>
                        {fmtDate(x.current_value.draw_date)} <Numbers n={x.current_value.numbers} />
                      </td>
                      <td className="small">{fmtDateTime(x.detected_at)}</td>
                      <td className="small">{x.resolution_note ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )
          }
        </AsyncView>
      </Card>
      <Card title="Quarentena">
        <AsyncView state={quar.state} onRetry={quar.reload} what="A quarentena">
          {(q) =>
            q.items.length === 0 ? (
              <Empty>Nenhuma linha em quarentena.</Empty>
            ) : (
              <Table caption="Linhas em quarentena">
                <thead>
                  <tr>
                    <th>Modalidade</th>
                    <th>Concurso</th>
                    <th>Tipo</th>
                    <th>Motivo</th>
                    <th className="r">Linha</th>
                    <th>Criada</th>
                  </tr>
                </thead>
                <tbody>
                  {q.items.map((x) => (
                    <tr key={x.id}>
                      <td>{LOTTERY_NAMES[x.lottery_slug] ?? x.lottery_slug}</td>
                      <td className="num">{x.contest ?? '—'}</td>
                      <td>{x.kind}</td>
                      <td>{x.reason}</td>
                      <td className="r num">{x.source_line ?? '—'}</td>
                      <td className="small">{fmtDateTime(x.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )
          }
        </AsyncView>
      </Card>
      <Card title="Execuções de coleta">
        <AsyncView state={runs.state} onRetry={runs.reload} what="As execuções de coleta">
          {(r) =>
            r.items.length === 0 ? (
              <Empty>Nenhuma execução registrada.</Empty>
            ) : (
              <Table caption="Execuções de coleta">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Modalidade</th>
                    <th>Status</th>
                    <th>Início</th>
                    <th className="r">Linhas</th>
                    <th className="r">Novas</th>
                    <th className="r">Divergentes</th>
                    <th className="r">Quarentena</th>
                    <th>Erro</th>
                  </tr>
                </thead>
                <tbody>
                  {r.items.map((x) => (
                    <tr key={x.id}>
                      <td className="num">{x.id}</td>
                      <td>{LOTTERY_NAMES[x.lottery_slug] ?? x.lottery_slug}</td>
                      <td>
                        <Tag tone={x.status === 'succeeded' ? 'good' : x.status === 'failed' ? 'bad' : 'info'}>{STATUS_LABELS[x.status] ?? x.status}</Tag>
                      </td>
                      <td className="small">{fmtDateTime(x.started_at)}</td>
                      <td className="r num">{fmtInt(x.row_count)}</td>
                      <td className="r num">{fmtInt(x.inserted_count)}</td>
                      <td className="r num">{fmtInt(x.divergent_count)}</td>
                      <td className="r num">{fmtInt(x.quarantined_count)}</td>
                      <td className="small">{x.error_message ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )
          }
        </AsyncView>
      </Card>
      <Card title="Jobs">
        <AsyncView state={jobs.state} onRetry={jobs.reload} what="Os jobs">
          {(j) =>
            j.items.length === 0 ? (
              <Empty>Nenhum job registrado.</Empty>
            ) : (
              <Table caption="Jobs">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Tipo</th>
                    <th>Modalidade</th>
                    <th>Status</th>
                    <th className="r">Tentativas</th>
                    <th>Criado</th>
                    <th>Erro</th>
                  </tr>
                </thead>
                <tbody>
                  {j.items.map((x) => (
                    <tr key={x.id}>
                      <td className="num">{x.id}</td>
                      <td>{x.kind}</td>
                      <td>{x.lottery_slug ? (LOTTERY_NAMES[x.lottery_slug] ?? x.lottery_slug) : '—'}</td>
                      <td>
                        <Tag tone={x.status === 'failed' ? 'bad' : x.status === 'succeeded' ? 'good' : 'info'}>{STATUS_LABELS[x.status] ?? x.status}</Tag>
                      </td>
                      <td className="r num">{x.attempts}</td>
                      <td className="small">{fmtDateTime(x.created_at)}</td>
                      <td className="small">{x.error ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )
          }
        </AsyncView>
      </Card>
      <Card title="Ferramentas locais">
        <Notice tone="info">Links abertos em nova aba; exigem autenticação própria e só respondem na máquina local com os serviços em execução.</Notice>
        <ul className="bullets">
          <li>
            <a href="http://127.0.0.1:8978" target="_blank" rel="noopener noreferrer">
              CloudBeaver (banco de dados) — http://127.0.0.1:8978
            </a>
          </li>
          <li>
            <a href="https://127.0.0.1:9443" target="_blank" rel="noopener noreferrer">
              Portainer (contêineres) — https://127.0.0.1:9443
            </a>
          </li>
        </ul>
      </Card>
    </>
  );
}
