import Fastify from 'fastify';
import { afterEach, describe, expect, it } from 'vitest';
import { MODELS, registerExperimentRoutes } from '../src/experiments.js';
import type { Queryable } from '../src/draws.js';

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
  await registerExperimentRoutes(app, d);
  await app.ready();
  return app;
}
afterEach(async () => {
  await Promise.all(apps.splice(0).map((a) => a.close()));
});
const H = { 'x-requested-with': 'cassino' };

describe('modelos', () => {
  it('lista baseline e modelos experimentais com rótulo probabilístico', async () => {
    const res = await (await build(db(() => []))).inject({ url: '/api/models' });
    const items = res.json().items;
    expect(items.map((m: any) => m.name)).toContain('uniform_baseline');
    expect(items.find((m: any) => m.name === 'delay_overdue')).toMatchObject({ probabilistic: false, experimental: true });
    expect(items.length).toBe(MODELS.length);
  });
});

describe('POST /api/experiments', () => {
  const ok = () => db(() => [{ experiment_id: '5', job_id: '9' }]);

  it('exige cabeçalho', async () => {
    const res = await (await build(ok())).inject({ method: 'POST', url: '/api/experiments', payload: { kind: 'backtest', lottery: 'quina' } });
    expect(res.statusCode).toBe(403);
  });

  it('backtest com defaults: enfileira config validada e devolve a semente usada', async () => {
    const d = ok();
    const res = await (await build(d)).inject({ method: 'POST', url: '/api/experiments', headers: H, payload: { kind: 'backtest', lottery: 'quina', seed: 42 } });
    expect(res.statusCode).toBe(202);
    expect(res.json()).toMatchObject({ experiment_id: '5', job_id: '9', seed: 42 });
    const [kind, lottery, config, seed, models] = d.calls[0]!.values as [string, string, string, number, string[]];
    expect([kind, lottery, seed]).toEqual(['backtest', 'quina', 42]);
    expect(JSON.parse(config)).toMatchObject({ test_contests: 500, tickets_per_contest: 10, seeds: 5, baseline_replicates: 500, refit_every: 50 });
    expect(models).toContain('ridge_logit');
    expect(models).not.toContain('uniform_baseline');
  });

  it('monte carlo', async () => {
    const d = ok();
    const res = await (await build(d)).inject({
      method: 'POST', url: '/api/experiments', headers: H,
      payload: { kind: 'montecarlo', lottery: 'megasena', tickets_per_contest: 10, contests: 100, replicates: 100 },
    });
    expect(res.statusCode).toBe(202);
    expect(d.calls[0]!.values![4]).toEqual(['montecarlo']);
  });

  it.each([
    ['kind desconhecido', { kind: 'x', lottery: 'quina' }],
    ['modelo inválido', { kind: 'backtest', lottery: 'quina', models: ['magic'] }],
    ['baseline como modelo', { kind: 'backtest', lottery: 'quina', models: ['uniform_baseline'] }],
    ['test_contests fora', { kind: 'backtest', lottery: 'quina', test_contests: 5 }],
    ['campo extra', { kind: 'backtest', lottery: 'quina', foo: 1 }],
    ['linhas acima do limite', { kind: 'backtest', lottery: 'quina', test_contests: 1000, tickets_per_contest: 50 }],
    ['montecarlo incompleto', { kind: 'montecarlo', lottery: 'quina', contests: 10 }],
    ['replicates alto', { kind: 'montecarlo', lottery: 'quina', tickets_per_contest: 1, contests: 10, replicates: 5000 }],
  ])('rejeita %s', async (_n, payload) => {
    const d = ok();
    const res = await (await build(d)).inject({ method: 'POST', url: '/api/experiments', headers: H, payload });
    expect(res.statusCode).toBe(400);
    expect(d.calls).toHaveLength(0);
  });

  it('429 quando a fila de experimentos está cheia', async () => {
    const res = await (await build(db(() => []))).inject({ method: 'POST', url: '/api/experiments', headers: H, payload: { kind: 'backtest', lottery: 'quina' } });
    expect(res.statusCode).toBe(429);
  });
});

describe('GET /api/experiments', () => {
  it('lista e detalha; resultados negativos são devolvidos junto com os positivos', async () => {
    const exp = { id: '5', kind: 'backtest', lottery_slug: 'quina', status: 'succeeded', conclusion: { verdict: 'no_evidence_of_advantage', summary: 's', limitations: ['l'] } };
    const results = [
      { model_name: 'freq_all', metric_name: 'mean_hits_per_ticket', verdict: 'worse_than_baseline' },
      { model_name: 'ridge_logit', metric_name: 'log_loss', verdict: 'better_not_significant' },
    ];
    const d = db((t) => (t.includes('FROM experiment_result') ? results : t.includes('WHERE e.experiment_id') ? [exp] : []));
    const app = await build(d);
    const res = await app.inject({ url: '/api/experiments/5' });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.results).toHaveLength(2);
    expect(body.conclusion.verdict).toBe('no_evidence_of_advantage');
    expect(body.disclaimer).toMatch(/nenhum modelo comprovou/);
    expect((await app.inject({ url: '/api/experiments/abc' })).statusCode).toBe(400);
    expect((await (await build(db(() => []))).inject({ url: '/api/experiments/7' })).statusCode).toBe(404);
    expect((await app.inject({ url: '/api/experiments?status=zzz' })).statusCode).toBe(400);
    expect((await app.inject({ url: '/api/experiments?limit=5' })).statusCode).toBe(200);
  });
});

describe('sugestões', () => {
  it('POST converte orçamento em nº de bilhetes pelo preço do banco', async () => {
    const d = db((t) => (t.includes('simple_price') ? [{ simple_price: '3.00' }] : [{ suggestion_set_id: '3', job_id: '4' }]));
    const res = await (await build(d)).inject({ method: 'POST', url: '/api/suggestions', headers: H, payload: { lottery: 'quina', strategy: 'diversity', budget: 10 } });
    expect(res.statusCode).toBe(202);
    expect(res.json()).toMatchObject({ suggestion_set_id: '3', ticket_count: 3 });
    expect(d.calls[1]!.values![4]).toBe(3);
  });

  it.each([
    ['orçamento insuficiente', { lottery: 'quina', strategy: 'diversity', budget: 1 }],
    ['estratégia inválida', { lottery: 'quina', strategy: 'palpite' }],
    ['tickets e budget', { lottery: 'quina', strategy: 'diversity', tickets: 2, budget: 10 }],
    ['acima de 200', { lottery: 'quina', strategy: 'diversity', tickets: 201 }],
  ])('rejeita %s', async (_n, payload) => {
    const d = db(() => [{ simple_price: '3.00' }]);
    const res = await (await build(d)).inject({ method: 'POST', url: '/api/suggestions', headers: H, payload });
    expect(res.statusCode).toBe(400);
  });

  it('GET devolve probabilidade exata e deixa claro que não há vantagem validada', async () => {
    const d = db((t) =>
      t.includes('FROM suggestion_set')
        ? [{ id: '3', lottery_slug: 'quina', strategy: 'diversity', ticket_count: 2, status: 'succeeded' }]
        : [
            { position: 1, numbers: [1, 2, 3, 4, 5], heuristic_score: 1, score_interpretation: 'x', jackpot_numerator: '1', jackpot_denominator: '24040016', cost: '3.00' },
            { position: 2, numbers: [6, 7, 8, 9, 10], heuristic_score: 0.8, score_interpretation: 'x', jackpot_numerator: '1', jackpot_denominator: '24040016', cost: '3.00' },
          ],
    );
    const body = (await (await build(d)).inject({ url: '/api/suggestions/3' })).json();
    expect(body.predictive_advantage_validated).toBe(false);
    expect(body.illustrative_only).toBe(true);
    expect(body.set.jackpot_probability).toMatchObject({ numerator: '2', denominator: '24040016' });
    expect(body.set.jackpot_probability.probability).toBeCloseTo(2 / 24040016, 12);
    expect(body.tickets[0].exact_jackpot_probability).toEqual({ numerator: '1', denominator: '24040016' });
  });
});
