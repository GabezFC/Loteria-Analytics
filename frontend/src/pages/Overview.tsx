import { api } from '../api/client';
import { useApi } from '../lib/useApi';
import { AsyncView, Card, Notice, PageHeader, Skeleton, Stat, Tag } from '../components/ui';
import { fmtDate, fmtDateTime, fmtInt } from '../lib/format';
import { href } from '../lib/router';
import { STATUS_LABELS } from '../lib/names';
import type { IngestionLottery, Job } from '../api/types';

function Health({ ing }: { ing: IngestionLottery }) {
  const c = ing.collector;
  const problems = ing.gap_count + ing.open_divergences + ing.quarantined_rows;
  return (
    <dl className="kv">
      <div>
        <dt>Última coleta</dt>
        <dd>{fmtDateTime(c?.last_success_at ?? null)}</dd>
      </div>
      <div>
        <dt>Falhas seguidas</dt>
        <dd>
          <Tag tone={c && c.consecutive_failures > 0 ? 'bad' : 'good'}>{c ? fmtInt(c.consecutive_failures) : 'sem coletor'}</Tag>
        </dd>
      </div>
      <div>
        <dt>Divergências abertas</dt>
        <dd>
          <Tag tone={ing.open_divergences > 0 ? 'warn' : 'good'}>{fmtInt(ing.open_divergences)}</Tag>
        </dd>
      </div>
      <div>
        <dt>Lacunas</dt>
        <dd>
          <Tag tone={ing.gap_count > 0 ? 'warn' : 'good'}>{fmtInt(ing.gap_count)}</Tag>
        </dd>
      </div>
      <div>
        <dt>Quarentena</dt>
        <dd>
          <Tag tone={ing.quarantined_rows > 0 ? 'warn' : 'good'}>{fmtInt(ing.quarantined_rows)}</Tag>
        </dd>
      </div>
      {c?.last_error && (
        <div className="kv-wide">
          <dt>Último erro</dt>
          <dd className="small">{c.last_error}</dd>
        </div>
      )}
      <div className="kv-wide">
        <dd className="small muted">{problems === 0 ? 'Integridade sem pendências.' : 'Há pendências — veja Administração.'}</dd>
      </div>
    </dl>
  );
}

function JobRow({ j }: { j: Job }) {
  return (
    <li>
      <Tag tone={j.status === 'failed' ? 'bad' : j.status === 'succeeded' ? 'good' : 'info'}>{STATUS_LABELS[j.status] ?? j.status}</Tag> <strong>{j.kind}</strong>
      {j.lottery_slug ? ' · ' + j.lottery_slug : ''} <span className="muted small">{fmtDateTime(j.created_at)}</span>
    </li>
  );
}

export function Overview() {
  const lot = useApi((s) => api.lotteries(s), [], { key: 'lotteries' });
  const ing = useApi((s) => api.ingestionStatus(s), [], { key: 'ingestion-status' });
  const jobs = useApi((s) => api.jobs({ limit: 6 }, s), [], { key: 'jobs-6', poll: 15000 });

  return (
    <>
      <PageHeader title="Visão geral" subtitle="Situação dos dados oficiais e da coleta, por modalidade." />
      <Notice tone="info" title="Atualização manual:">
        a coleta automática roda periodicamente. Para forçar uma nova coleta, use o botão “Atualizar agora” em <a href={href('/admin')}>Administração</a>.
      </Notice>
      <AsyncView state={lot.state} onRetry={lot.reload} what="A lista de modalidades" skeleton={<Skeleton lines={6} height={22} />}>
        {(l) => (
          <div className="grid grid-3">
            {l.items.map((x) => {
              const g = ing.state.status === 'ok' ? ing.state.data.lotteries.find((i) => i.lottery_slug === x.slug) : undefined;
              return (
                <Card key={x.slug} title={x.name}>
                  <div className="stats">
                    <Stat label="Concursos validados" value={fmtInt(x.draw_count)} />
                    <Stat label="Último concurso" value={x.last_contest !== null ? '#' + fmtInt(x.last_contest) : '—'} hint={fmtDate(x.last_draw_date)} />
                  </div>
                  {g ? <Health ing={g} /> : ing.state.status === 'error' ? <p className="muted small">Saúde da coleta indisponível: {ing.state.error.message}</p> : <Skeleton lines={3} />}
                  <p>
                    <a className="btn btn-primary" href={href('/' + x.slug)}>
                      Ver estatísticas
                    </a>
                  </p>
                </Card>
              );
            })}
          </div>
        )}
      </AsyncView>
      <Card title="Jobs recentes">
        <AsyncView state={jobs.state} onRetry={jobs.reload} what="A lista de jobs">
          {(j) => (j.items.length === 0 ? <p className="muted">Nenhum job registrado.</p> : <ul className="list">{j.items.map((x) => <JobRow key={x.id} j={x} />)}</ul>)}
        </AsyncView>
      </Card>
    </>
  );
}
