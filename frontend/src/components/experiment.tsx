import { api } from '../api/client';
import type { ExperimentDetail, ExperimentSummary, Progress } from '../api/types';
import { useApi } from '../lib/useApi';
import { AsyncView, Empty, Tag } from './ui';
import { fmtDateTime, fmtInt } from '../lib/format';
import { LOTTERY_NAMES, STATUS_LABELS, VERDICT_LABELS } from '../lib/names';
import { href } from '../lib/router';

export function isFinished(status: string | undefined): boolean {
  return status === 'succeeded' || status === 'failed';
}

export function ProgressBar({ progress, status }: { progress: Progress | null; status: string }) {
  if (!progress) return <span className="muted small">{STATUS_LABELS[status] ?? status}</span>;
  const pct = progress.total > 0 ? Math.min(100, Math.round((progress.done / progress.total) * 100)) : 0;
  return (
    <div className="progress">
      <div className="progress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={'Progresso: ' + progress.stage}>
        <span style={{ width: pct + '%' }} />
      </div>
      <span className="small muted">
        {progress.stage} · {fmtInt(progress.done)}/{fmtInt(progress.total)} ({pct}%)
      </span>
    </div>
  );
}

/** Tons/ícones distintos e de igual destaque: resultado negativo não some e positivo não é só “verde”. */
export function VerdictTag({ verdict }: { verdict: string | null }) {
  if (!verdict) return <Tag>sem veredito</Tag>;
  const label = VERDICT_LABELS[verdict] ?? verdict;
  const worse = verdict === 'worse_than_baseline';
  const same = verdict === 'indistinguishable' || verdict === 'better_not_significant';
  return (
    <span className={'verdict ' + (worse ? 'verdict-neg' : same ? 'verdict-neu' : 'verdict-pos')}>
      <span aria-hidden="true">{worse ? '▼' : same ? '≈' : '▲'}</span> {label}
    </span>
  );
}

export function ExperimentList({ kind, base, lottery }: { kind: 'backtest' | 'montecarlo'; base: string; lottery?: string }) {
  const { state, reload } = useApi((s) => api.experiments({ kind, limit: 15 }, s), [kind, lottery], {
    poll: (d: { items: ExperimentSummary[] } | null) => (d && d.items.some((i) => !isFinished(i.status)) ? 3000 : 20000),
  });
  return (
    <AsyncView state={state} onRetry={reload} what="A lista de experimentos">
      {(l) =>
        l.items.length === 0 ? (
          <Empty>Nenhum experimento ainda.</Empty>
        ) : (
          <ul className="list list-rich">
            {l.items.map((x) => (
              <li key={x.id}>
                <div>
                  <a href={href(base + '/' + x.id)}>#{x.id}</a> · {LOTTERY_NAMES[x.lottery_slug] ?? x.lottery_slug} · <Tag tone={x.status === 'failed' ? 'bad' : x.status === 'succeeded' ? 'neutral' : 'info'}>{STATUS_LABELS[x.status] ?? x.status}</Tag>{' '}
                  <span className="muted small">{fmtDateTime(x.created_at)}</span>
                </div>
                {!isFinished(x.status) && <ProgressBar progress={x.progress} status={x.status} />}
                {x.verdict_summary && <div className="small">{x.verdict_summary}</div>}
              </li>
            ))}
          </ul>
        )
      }
    </AsyncView>
  );
}

/** Carrega um experimento com polling até terminar. */
export function useExperiment(id: string) {
  return useApi<ExperimentDetail>((s) => api.experiment(id, s), [id], {
    poll: (d) => (d && isFinished(d.experiment.status) ? null : 2500),
  });
}
