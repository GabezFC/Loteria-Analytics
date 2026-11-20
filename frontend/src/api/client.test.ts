import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, buildQuery, request } from './client';

function mockFetch(status: number, body: unknown, raw = false) {
  const fn = vi.fn(async (_url: string, _init?: RequestInit) => new Response(raw ? String(body) : JSON.stringify(body), { status }));
  vi.stubGlobal('fetch', fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe('cliente de API', () => {
  it('monta a query ignorando valores vazios', () => {
    expect(buildQuery({ a: 1, b: undefined, c: '', d: 'x y' })).toBe('?a=1&d=x+y');
    expect(buildQuery()).toBe('');
  });

  it('GET usa /api, Accept JSON e não envia X-Requested-With', async () => {
    const f = mockFetch(200, { items: [] });
    await api.lotteries();
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/lotteries');
    expect((init.headers as Record<string, string>).Accept).toBe('application/json');
    expect((init.headers as Record<string, string>)['X-Requested-With']).toBeUndefined();
  });

  it('POST envia X-Requested-With e Content-Type JSON', async () => {
    const f = mockFetch(202, { job_id: '7', status: 'pending' });
    const r = await api.triggerIngestion('quina');
    expect(r.job_id).toBe('7');
    const init = f.mock.calls[0]?.[1] as RequestInit;
    const h = init.headers as Record<string, string>;
    expect(h['X-Requested-With']).toBe('cassino');
    expect(h['Content-Type']).toBe('application/json');
    expect(init.body).toBe('{"lottery":"quina"}');
  });

  it('erro 4xx expõe status e mensagem do servidor', async () => {
    mockFetch(409, { error: 'coleta pendente' });
    await expect(api.triggerIngestion()).rejects.toMatchObject({ name: 'ApiError', status: 409, message: 'coleta pendente' });
  });

  it('erro 429 é propagado', async () => {
    mockFetch(429, { error: 'limite' });
    await expect(api.triggerIngestion()).rejects.toMatchObject({ status: 429 });
  });

  it('404 de rota inexistente (formato Fastify) vira "indisponível"', async () => {
    mockFetch(404, { message: 'Route GET:/api/models not found', error: 'Not Found', statusCode: 404 });
    const err = await api.models().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).unavailable).toBe(true);
  });

  it('erro 5xx com corpo não JSON usa mensagem genérica', async () => {
    mockFetch(502, '<html>bad gateway</html>', true);
    await expect(request('/health')).rejects.toMatchObject({ status: 502, message: 'Erro HTTP 502.' });
  });

  it('503 também é "indisponível"', async () => {
    mockFetch(503, { error: 'ainda não calculado' });
    const err = (await api.stats('quina', 'all').catch((e: unknown) => e)) as ApiError;
    expect(err.unavailable).toBe(true);
    expect(err.message).toBe('ainda não calculado');
  });

  it('valida o formato básico: lista sem "items" é rejeitada', async () => {
    mockFetch(200, { foo: 1 });
    await expect(api.lotteries()).rejects.toMatchObject({ message: expect.stringContaining('falta "items"') });
  });

  it('valida o formato básico: probabilidades sem "tiers" é rejeitada', async () => {
    mockFetch(200, { lottery: 'quina' });
    await expect(api.probabilities({ lottery: 'quina' })).rejects.toBeInstanceOf(ApiError);
  });

  it('200 com corpo não JSON é erro', async () => {
    mockFetch(200, 'ok', true);
    await expect(request('/health')).rejects.toMatchObject({ message: expect.stringContaining('JSON') });
  });

  it('falha de rede vira ApiError status 0', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('fail'))));
    await expect(request('/health')).rejects.toMatchObject({ status: 0, message: 'Não foi possível contatar a API.' });
  });

  it('timeout aborta a requisição', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((_u: string, init?: RequestInit) => new Promise((_res, rej) => init?.signal?.addEventListener('abort', () => rej(new DOMException('abort', 'AbortError'))))),
    );
    await expect(request('/health', { timeoutMs: 20 })).rejects.toMatchObject({ message: 'Tempo esgotado ao contatar a API.' });
  });

  it('propaga o abort do chamador (sem virar ApiError)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((_u: string, init?: RequestInit) => new Promise((_res, rej) => init?.signal?.addEventListener('abort', () => rej(new DOMException('abort', 'AbortError'))))),
    );
    const ctl = new AbortController();
    const p = request('/health', { signal: ctl.signal });
    ctl.abort();
    await expect(p).rejects.toMatchObject({ name: 'AbortError' });
  });
});
