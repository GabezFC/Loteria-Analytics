import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../api/client';

// Cache simples em memória com TTL.
const cache = new Map<string, { at: number; value: unknown }>();
export const CACHE_TTL_MS = 60_000;

export function clearCache(prefix?: string): void {
  if (!prefix) cache.clear();
  else for (const k of [...cache.keys()]) if (k.startsWith(prefix)) cache.delete(k);
}

export type Async<T> =
  | { status: 'loading'; data: T | null }
  | { status: 'ok'; data: T }
  | { status: 'error'; error: ApiError; data: T | null };

interface Opts<T> {
  /** Chave de cache; sem chave, não usa cache. */
  key?: string;
  /** Polling: ms fixos ou função (dados atuais → ms, ou null para parar). */
  poll?: number | ((data: T | null) => number | null);
  enabled?: boolean;
}

function toApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(e instanceof Error ? e.message : 'Erro desconhecido.', 0);
}

export function useApi<T>(fetcher: (signal: AbortSignal) => Promise<T>, deps: readonly unknown[], opts: Opts<T> = {}) {
  const { key, poll, enabled = true } = opts;
  const [state, setState] = useState<Async<T>>(() => {
    const hit = key ? cache.get(key) : undefined;
    return hit && Date.now() - hit.at < CACHE_TTL_MS
      ? { status: 'ok', data: hit.value as T }
      : { status: 'loading', data: null };
  });
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const pollRef = useRef(poll);
  pollRef.current = poll;

  const reload = useCallback(() => {
    if (key) cache.delete(key);
    setTick((t) => t + 1);
  }, [key]);

  useEffect(() => {
    if (!enabled) return;
    const ctl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const hit = key ? cache.get(key) : undefined;
    const fresh = hit !== undefined && Date.now() - hit.at < CACHE_TTL_MS;
    if (hit !== undefined && fresh) setState({ status: 'ok', data: hit.value as T });
    else setState((s) => ({ status: 'loading', data: s.data }));

    const schedule = (data: T | null) => {
      const p = pollRef.current;
      const ms = typeof p === 'function' ? p(data) : (p ?? null);
      if (ms && !ctl.signal.aborted) timer = setTimeout(run, ms);
    };
    const run = () => {
      fetcherRef
        .current(ctl.signal)
        .then((data) => {
          if (ctl.signal.aborted) return;
          if (key) cache.set(key, { at: Date.now(), value: data });
          setState({ status: 'ok', data });
          schedule(data);
        })
        .catch((e: unknown) => {
          if (ctl.signal.aborted) return;
          setState((s) => ({ status: 'error', error: toApiError(e), data: s.data }));
          schedule(null);
        });
    };
    if (hit !== undefined && fresh) schedule(hit.value as T);
    else run();
    return () => {
      ctl.abort();
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, key, enabled, tick]);

  return { state, reload };
}
