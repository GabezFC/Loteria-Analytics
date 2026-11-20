import Fastify from 'fastify';
import { afterEach, describe, expect, it } from 'vitest';
import { registerOpsRoutes, registerProbabilityRoutes, registerStatsRoutes } from '../src/api.js';
import { registerDrawRoutes, type Queryable } from '../src/draws.js';

type Handler = (text: string, values?: unknown[]) => any[];
function db(handler: Handler): Queryable & { calls: Array<{ text: string; values?: unknown[] }> } {
  const calls: Array<{ text: string; values?: unknown[] }> = [];
  return {
    calls,
    async query(text, values) {
      calls.push({ text, values });
      return { rows: handler(text, values) };
    },
  };
}
const apps: Array<ReturnType<typeof Fastify>> = [];
async function build(d: Queryable) {
  const app = Fastify();
  apps.push(app);
  await registerDrawRoutes(app, d);
  await registerOpsRoutes(app, d);
  await registerProbabilityRoutes(app, d);
  await registerStatsRoutes(app, d);
  await app.ready();
  return app;
}
afterEach(async () => {
  await Promise.all(apps.splice(0).map((a) => a.close()));
});

const HEADERS = { 'x-requested-with': 'cassino' };
const MEGA = { slug: 'megasena', pool_size: 60, draw_size: 6, min_bet_size: 6, max_bet_size: 20, simple_price: '6.00', price_source: 'x' };
const megaRows = [6, 5, 4, 3, 2, 1, 0].map((h) => ({
  hits: h,
  is_prize_tier: h >= 4,
  exact_numerator: '1',
  exact_denominator: '50063860',
  at_least_numerator: '1',
  probability: 1 / 50063860,
  at_least_probability: 1 / 50063860,
  simple_games: '1',
  cost: '6.00',
  formula_version: 'v1',
}));
const probDb = () => db((t) => (t.includes('FROM lottery_type') ? [MEGA] : t.includes('probability_table') ? megaRows : []));

describe('GET /api/probabilities', () => {
  it('devolve faixas, premissas e fração exata', async () => {
    const res = await (await build(probDb())).inject({ url: '/api/probabilities?lottery=megasena' });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.total_combinations).toBe('50063860');
    expect(body.tiers[0]).toMatchObject({ hits: 6, exact: { numerator: '1', denominator: '50063860' } });
    expect(body.assumptions.length).toBeGreaterThan(2);
  });

  it('m bilhetes distintos = m/C(N,k) e vários concursos usam 1-(1-p)^c', async () => {
    const app = await build(probDb());
    const one = (await app.inject({ url: '/api/probabilities?lottery=megasena&tickets=10' })).json();
    expect(one.tickets_jackpot.fraction).toEqual({ numerator: '10', denominator: '50063860' });
    expect(one.tickets_jackpot.probability).toBeCloseTo(10 / 50063860, 15);
    const many = (await app.inject({ url: '/api/probabilities?lottery=megasena&tickets=1&contests=2' })).json();
    expect(many.tickets_jackpot.probability).toBeCloseTo(1 - (1 - 1 / 50063860) ** 2, 14);
  });

  it('orçamento converte em bilhetes pelo preço parametrizado', async () => {
    const r = (await (await build(probDb())).inject({ url: '/api/probabilities?lottery=megasena&budget=61' })).json();
    expect(r.tickets_jackpot).toMatchObject({ count: '10', spent: '60.00' });
  });

  it.each([
    ['bet_size fora da faixa', '&bet_size=21'],
    ['tickets com aposta múltipla', '&bet_size=7&tickets=2'],
    ['tickets e budget juntos', '&tickets=1&budget=10'],
    ['tickets acima de C(N,k)', '&tickets=99999999'],
    ['parâmetro desconhecido', '&x=1'],
    ['hits inválido', '&hits=9'],
  ])('rejeita %s', async (_n, qs) => {
    const res = await (await build(probDb())).inject({ url: `/api/probabilities?lottery=megasena${qs}` });
    expect(res.statusCode).toBe(400);
  });

  it('lottery obrigatória e válida', async () => {
    const app = await build(probDb());
    expect((await app.inject({ url: '/api/probabilities' })).statusCode).toBe(400);
    expect((await app.inject({ url: '/api/probabilities?lottery=loto' })).statusCode).toBe(400);
  });

  it('503 quando a tabela ainda não foi calculada', async () => {
    const res = await (await build(db((t) => (t.includes('FROM lottery_type') ? [MEGA] : [])))).inject({ url: '/api/probabilities?lottery=megasena' });
    expect(res.statusCode).toBe(503);
  });
});

describe('GET /api/stats*', () => {
  it('404 sem análise; nunca fabrica dados', async () => {
    const res = await (await build(db(() => []))).inject({ url: '/api/stats?lottery=quina&window=30' });
    expect(res.statusCode).toBe(404);
  });

  it('monta resposta com aviso de não-previsão', async () => {
    const d = db((t) => {
      if (t.includes('FROM analysis_run')) return [{ id: '7', window_label: 'all' }];
      if (t.includes('FROM number_stat')) return [{ number: 1, frequency: 3 }];
      if (t.includes('FROM analysis_result')) return [{ kind: 'distributions', payload: { sum: {} } }, { kind: 'meta', payload: { sample_size: 3 } }];
      return [];
    });
    const res = await (await build(d)).inject({ url: '/api/stats?lottery=quina' });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.numbers).toHaveLength(1);
    expect(body.disclaimer).toMatch(/Não são probabilidades/);
    expect(d.calls[0]?.values).toEqual(['quina', 'all']);
  });

  it.each(['?lottery=quina&window=7', '?lottery=quina&foo=1', '?window=all', '?lottery=quina&window=all&size=5'])('valida %s', async (qs) => {
    const res = await (await build(db(() => []))).inject({ url: `/api/stats/combinations${qs}` });
    expect(res.statusCode).toBe(400);
  });
});

describe('operações de coleta', () => {
  it('POST /api/admin/ingestion exige cabeçalho e enfileira job', async () => {
    const d = db(() => [{ id: '12' }]);
    const app = await build(d);
    expect((await app.inject({ method: 'POST', url: '/api/admin/ingestion', payload: {} })).statusCode).toBe(403);
    const ok = await app.inject({ method: 'POST', url: '/api/admin/ingestion', headers: HEADERS, payload: { lottery: 'quina' } });
    expect(ok.statusCode).toBe(202);
    expect(ok.json()).toEqual({ job_id: '12', status: 'pending' });
    expect(d.calls.at(-1)?.values).toEqual(['quina']);
  });

  it('409 quando já há coleta pendente e 400 para modalidade inválida', async () => {
    const app = await build(db(() => []));
    expect((await app.inject({ method: 'POST', url: '/api/admin/ingestion', headers: HEADERS, payload: {} })).statusCode).toBe(409);
    expect((await app.inject({ method: 'POST', url: '/api/admin/ingestion', headers: HEADERS, payload: { lottery: 'x' } })).statusCode).toBe(400);
  });

  it('limita a 6 disparos por minuto', async () => {
    const app = await build(db(() => [{ id: '1' }]));
    const codes: number[] = [];
    for (let i = 0; i < 8; i++) codes.push((await app.inject({ method: 'POST', url: '/api/admin/ingestion', headers: HEADERS, payload: {} })).statusCode);
    expect(codes.filter((c) => c === 429).length).toBe(2);
  });

  it('GET /api/draws/:lottery/:contest devolve 404 quando inexistente', async () => {
    const res = await (await build(db(() => []))).inject({ url: '/api/draws/quina/999999' });
    expect(res.statusCode).toBe(404);
  });

  it('jobs e divergências validam enums', async () => {
    const app = await build(db(() => []));
    expect((await app.inject({ url: '/api/jobs?status=zzz' })).statusCode).toBe(400);
    expect((await app.inject({ url: '/api/ingestion/divergences?status=open' })).statusCode).toBe(200);
  });
});
