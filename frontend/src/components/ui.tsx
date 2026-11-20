import type { ReactNode } from 'react';
import type { Async } from '../lib/useApi';
import { ApiError } from '../api/client';
import { pad2 } from '../lib/format';

export function Card({ title, children, actions, className, id }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; className?: string; id?: string }) {
  return (
    <section className={'card' + (className ? ' ' + className : '')} aria-labelledby={id ? id + '-h' : undefined}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2 id={id ? id + '-h' : undefined}>{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {children && <div className="page-head-actions">{children}</div>}
    </div>
  );
}

export function Skeleton({ lines = 3, height = 16 }: { lines?: number; height?: number }) {
  return (
    <div className="skeleton" role="status" aria-label="Carregando">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton-line" style={{ height, width: 100 - ((i * 13) % 40) + '%' }} />
      ))}
    </div>
  );
}

export function ErrorBox({ error, onRetry, what }: { error: ApiError; onRetry?: () => void; what?: string }) {
  const unavailable = error.unavailable;
  return (
    <div className={'state ' + (unavailable ? 'state-info' : 'state-error')} role={unavailable ? 'status' : 'alert'}>
      <strong>{unavailable ? 'Ainda não disponível' : 'Falha ao carregar'}</strong>
      <p>
        {unavailable
          ? (what ?? 'Este recurso') + ' ainda não está disponível no servidor ou ainda não foi calculado. Nenhum dado foi inventado para preencher a tela.'
          : error.message}
      </p>
      {unavailable && error.message && !/^Erro HTTP/.test(error.message) && <p className="muted small">Detalhe: {error.message}</p>}
      {onRetry && (
        <button type="button" className="btn btn-ghost" onClick={onRetry}>
          Tentar novamente
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="state state-empty">{children}</div>;
}

/** Renderiza loading/erro/ok de forma uniforme. */
export function AsyncView<T>({
  state,
  children,
  onRetry,
  what,
  skeleton,
}: {
  state: Async<T>;
  children: (data: T) => ReactNode;
  onRetry?: () => void;
  what?: string;
  skeleton?: ReactNode;
}) {
  if (state.status === 'ok') return <>{children(state.data)}</>;
  if (state.status === 'error') return <ErrorBox error={state.error} onRetry={onRetry} what={what} />;
  return <>{skeleton ?? <Skeleton lines={4} />}</>;
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value num">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function Balls({ numbers, highlight }: { numbers: number[]; highlight?: Set<number> }) {
  return (
    <span className="balls" aria-label={'Dezenas: ' + numbers.map(pad2).join(', ')}>
      {numbers.map((n) => (
        <span key={n} className={'ball num' + (highlight?.has(n) ? ' ball-hl' : '')}>
          {pad2(n)}
        </span>
      ))}
    </span>
  );
}

export function Tag({ tone = 'neutral', children }: { tone?: 'neutral' | 'good' | 'warn' | 'bad' | 'info'; children: ReactNode }) {
  return <span className={'tag tag-' + tone}>{children}</span>;
}

export function Notice({ tone = 'info', title, children }: { tone?: 'info' | 'warn'; title?: string; children: ReactNode }) {
  return (
    <aside className={'notice notice-' + tone} role="note">
      {title && <strong>{title}</strong>} {children}
    </aside>
  );
}

export const GLOBAL_DISCLAIMER =
  'Análise estatística de resultados oficiais. Sorteios são independentes; nenhum método aqui prevê resultados ou aumenta a chance de ganhar. Não há apostas reais.';

export function Field({ label, children, hint, htmlFor }: { label: string; children: ReactNode; hint?: string; htmlFor?: string }) {
  return (
    <label className="field" htmlFor={htmlFor}>
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function Table({ children, caption }: { children: ReactNode; caption?: string }) {
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={caption ?? 'Tabela'}>
      <table className="table">
        {caption && <caption className="sr-only">{caption}</caption>}
        {children}
      </table>
    </div>
  );
}
