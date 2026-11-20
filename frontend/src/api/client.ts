import type {
  Combinations,
  Divergence,
  DrawDetail,
  DrawList,
  ExperimentDetail,
  ExperimentRequest,
  ExperimentSummary,
  Health,
  Inference,
  InferenceResponse,
  IngestionLottery,
  IngestionRun,
  IngestionTrigger,
  Job,
  Lottery,
  LotteryInfo,
  ModelInfo,
  Probabilities,
  QuarantineRow,
  Stats,
  SuggestionDetail,
  SuggestionRequest,
  SuggestionSummary,
  WindowInfo,
} from './types';

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
  /** 404/501/503: recurso ainda não calculado ou não implementado. */
  get unavailable(): boolean {
    return this.status === 404 || this.status === 501 || this.status === 503;
  }
}

export const DEFAULT_TIMEOUT_MS = 20000;
export type Query = Record<string, string | number | boolean | undefined | null>;

export function buildQuery(query?: Query): string {
  if (!query) return '';
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === '') continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? '?' + s : '';
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** Extrai mensagem de erro de `{error}` / `{message}` do Fastify. */
export function errorMessage(body: unknown, fallback: string): string {
  if (isRecord(body)) {
    if (typeof body.error === 'string' && body.error && body.error !== 'Not Found') {
      return typeof body.message === 'string' ? body.message : body.error;
    }
    if (typeof body.message === 'string') return body.message;
  }
  return fallback;
}

interface RequestOptions {
  method?: 'GET' | 'POST';
  query?: Query;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', query, body, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = opts;
  const ctl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    ctl.abort();
  }, timeoutMs);
  const onAbort = () => ctl.abort();
  if (signal) {
    if (signal.aborted) ctl.abort();
    else signal.addEventListener('abort', onAbort, { once: true });
  }
  try {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (method === 'POST') {
      headers['Content-Type'] = 'application/json';
      headers['X-Requested-With'] = 'cassino';
    }
    const resp = await fetch('/api' + path + buildQuery(query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctl.signal,
    });
    let parsed: unknown = null;
    const text = await resp.text();
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        if (resp.ok) throw new ApiError('Resposta da API não é JSON válido.', resp.status);
      }
    }
    if (!resp.ok) {
      throw new ApiError(errorMessage(parsed, 'Erro HTTP ' + resp.status + '.'), resp.status);
    }
    if (parsed === null) throw new ApiError('Resposta vazia da API.', resp.status);
    return parsed as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (timedOut) throw new ApiError('Tempo esgotado ao contatar a API.', 0);
    if (signal?.aborted) throw e;
    throw new ApiError('Não foi possível contatar a API.', 0);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}

// ---- Validação básica de formato (falha cedo em vez de quebrar a renderização) ----
function requireKeys<T>(value: unknown, keys: string[], what: string): T {
  if (!isRecord(value)) throw new ApiError('Formato inesperado em ' + what + '.', 502);
  for (const k of keys) {
    if (!(k in value)) throw new ApiError('Formato inesperado em ' + what + ': falta "' + k + '".', 502);
  }
  return value as T;
}
export function requireItems<T>(value: unknown, what: string): { items: T[] } {
  const v = requireKeys<{ items: unknown }>(value, ['items'], what);
  if (!Array.isArray(v.items)) throw new ApiError('Formato inesperado em ' + what + ': "items" não é lista.', 502);
  return v as { items: T[] };
}

export const api = {
  health: (signal?: AbortSignal) =>
    request<Health>('/health', { signal }).then((v) => requireKeys<Health>(v, ['status'], 'health')),
  lotteries: (signal?: AbortSignal) =>
    request<unknown>('/lotteries', { signal }).then((v) => requireItems<LotteryInfo>(v, 'lotteries')),
  draws: (
    q: { lottery?: Lottery; limit?: number; offset?: number; contest?: number; date_from?: string; date_to?: string; numbers?: string },
    signal?: AbortSignal,
  ) =>
    request<unknown>('/draws', { query: q, signal }).then((v) =>
      requireKeys<DrawList>(v, ['items', 'total', 'limit', 'offset'], 'draws'),
    ),
  draw: (lottery: Lottery, contest: number, signal?: AbortSignal) =>
    request<unknown>('/draws/' + lottery + '/' + contest, { signal }).then((v) =>
      requireKeys<DrawDetail>(v, ['contest', 'numbers', 'prizes'], 'draw'),
    ),
  ingestionStatus: (signal?: AbortSignal) =>
    request<unknown>('/ingestion/status', { signal }).then((v) => {
      const r = requireKeys<{ lotteries: unknown }>(v, ['lotteries'], 'ingestion/status');
      if (!Array.isArray(r.lotteries)) throw new ApiError('Formato inesperado em ingestion/status.', 502);
      return r as { lotteries: IngestionLottery[] };
    }),
  ingestionRuns: (limit = 20, signal?: AbortSignal) =>
    request<unknown>('/ingestion/runs', { query: { limit }, signal }).then((v) => requireItems<IngestionRun>(v, 'runs')),
  divergences: (status?: 'open' | 'accepted' | 'rejected', limit = 50, signal?: AbortSignal) =>
    request<unknown>('/ingestion/divergences', { query: { status, limit }, signal }).then((v) =>
      requireItems<Divergence>(v, 'divergences'),
    ),
  quarantine: (limit = 50, signal?: AbortSignal) =>
    request<unknown>('/ingestion/quarantine', { query: { limit }, signal }).then((v) =>
      requireItems<QuarantineRow>(v, 'quarantine'),
    ),
  jobs: (q: { kind?: string; status?: string; limit?: number } = {}, signal?: AbortSignal) =>
    request<unknown>('/jobs', { query: q, signal }).then((v) => requireItems<Job>(v, 'jobs')),
  triggerIngestion: (lottery?: Lottery, signal?: AbortSignal) =>
    request<IngestionTrigger>('/admin/ingestion', { method: 'POST', body: lottery ? { lottery } : {}, signal }),
  probabilities: (
    q: { lottery: Lottery; bet_size?: number; hits?: number; tickets?: number; budget?: number; contests?: number },
    signal?: AbortSignal,
  ) =>
    request<unknown>('/probabilities', { query: q, signal }).then((v) =>
      requireKeys<Probabilities>(v, ['tiers', 'assumptions', 'bet_cost'], 'probabilities'),
    ),
  statsWindows: (lottery: Lottery, signal?: AbortSignal) =>
    request<unknown>('/stats/windows', { query: { lottery }, signal }).then((v) => requireItems<WindowInfo>(v, 'windows')),
  stats: (lottery: Lottery, window: string, signal?: AbortSignal) =>
    request<unknown>('/stats', { query: { lottery, window }, signal }).then((v) =>
      requireKeys<Stats>(v, ['analysis_run', 'numbers', 'distributions', 'meta'], 'stats'),
    ),
  inference: (lottery: Lottery, window: string, signal?: AbortSignal) =>
    request<unknown>('/stats/inference', { query: { lottery, window }, signal }).then((v) =>
      requireKeys<InferenceResponse>(v, ['analysis_run'], 'inference'),
    ),
  combinations: (
    lottery: Lottery,
    window: string,
    size: number,
    order: 'over' | 'under',
    limit = 30,
    signal?: AbortSignal,
  ) =>
    request<unknown>('/stats/combinations', { query: { lottery, window, size, order, limit }, signal }).then((v) =>
      requireKeys<Combinations>(v, ['items', 'meta'], 'combinations'),
    ),
  models: (signal?: AbortSignal) =>
    request<unknown>('/models', { signal }).then((v) => requireItems<ModelInfo>(v, 'models')),
  experiments: (q: { lottery?: Lottery; kind?: string; status?: string; limit?: number } = {}, signal?: AbortSignal) =>
    request<unknown>('/experiments', { query: q, signal }).then((v) => requireItems<ExperimentSummary>(v, 'experiments')),
  experiment: (id: string, signal?: AbortSignal) =>
    request<unknown>('/experiments/' + encodeURIComponent(id), { signal }).then((v) =>
      requireKeys<ExperimentDetail>(v, ['experiment', 'results'], 'experiment'),
    ),
  createExperiment: (body: ExperimentRequest, signal?: AbortSignal) =>
    request<{ experiment_id: string; job_id: string }>('/experiments', { method: 'POST', body, signal }),
  suggestions: (q: { lottery?: Lottery; limit?: number } = {}, signal?: AbortSignal) =>
    request<unknown>('/suggestions', { query: q, signal }).then((v) => requireItems<SuggestionSummary>(v, 'suggestions')),
  suggestion: (id: string, signal?: AbortSignal) =>
    request<unknown>('/suggestions/' + encodeURIComponent(id), { signal }).then((v) =>
      requireKeys<SuggestionDetail>(v, ['set', 'tickets'], 'suggestion'),
    ),
  createSuggestion: (body: SuggestionRequest, signal?: AbortSignal) =>
    request<{ suggestion_set_id: string; job_id: string }>('/suggestions', { method: 'POST', body, signal }),
};

export type { Inference };
