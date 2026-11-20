import { randomInt } from 'node:crypto';
import type { FastifyInstance } from 'fastify';
import { LOTTERY_SLUGS, MAX_LIMIT, notFound, rejectUnknownQuery, type Queryable } from './draws.js';

const lotteryEnum = { type: 'string', enum: [...LOTTERY_SLUGS] } as const;
const DISCLAIMER =
  'Análise exploratória: nenhum modelo comprovou vantagem preditiva. Sorteios justos são independentes; scores heurísticos NÃO são probabilidades de acerto.';

/** Catálogo estático (espelha workers/backtest.py::MODEL_CATALOG). */
export const MODELS = [
  { name: 'uniform_baseline', label: 'Baseline uniforme (aleatório)', family: 'baseline', description: 'Bilhetes aleatórios uniformes de mesmo custo; referência de todas as comparações.', experimental: false, probabilistic: true, default: true },
  { name: 'freq_all', label: 'Frequência histórica suavizada', family: 'frequency', description: 'p(i) = (f_i + a·k/N)/(n + a) usando todo o passado; encolhimento para a uniforme.', experimental: false, probabilistic: true, default: true },
  { name: 'freq_w100', label: 'Frequência — últimos 100 concursos', family: 'frequency', description: 'Mesma suavização, janela móvel de 100 concursos anteriores.', experimental: false, probabilistic: true, default: true },
  { name: 'freq_w30', label: 'Frequência — últimos 30 concursos', family: 'frequency', description: 'Janela móvel de 30 concursos (alta variância).', experimental: false, probabilistic: true, default: false },
  { name: 'delay_overdue', label: 'Atraso (dezenas "devidas")', family: 'delay', description: 'Peso crescente com o atraso atual (falácia do jogador): incluída para testar empiricamente; score, não probabilidade.', experimental: true, probabilistic: false, default: true },
  { name: 'ridge_logit', label: 'Regressão logística regularizada (ML)', family: 'ml', description: 'Logística ridge sobre frequências 10/30/100, atraso e repetição; reajustada periodicamente só com o passado.', experimental: true, probabilistic: true, default: true },
] as const;
const MODEL_NAMES = MODELS.filter((m) => m.name !== 'uniform_baseline').map((m) => m.name);
const STRATEGIES = ['uniform_random', 'diversity', 'frequency_weighted', 'delay_weighted'] as const;
const TS = (c: string) => `to_char(${c} AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')`;
const MAX_ACTIVE = 3;

export const EXPERIMENT_INSERT_SQL = `
WITH capacity AS (
  SELECT (SELECT COUNT(*) FROM experiment WHERE status IN ('pending','running')) < ${MAX_ACTIVE} AS ok
), e AS (
  INSERT INTO experiment(kind, lottery_slug, config, config_hash, seed, models)
  SELECT $1::text, $2::text, $3::jsonb, md5($3::jsonb::text), $4::bigint, $5::text[] FROM capacity WHERE ok
  RETURNING experiment_id
), j AS (
  INSERT INTO job(kind, lottery_slug, params)
  SELECT 'experiment', $2::text, jsonb_build_object('experiment_id', experiment_id) FROM e
  RETURNING job_id
)
SELECT e.experiment_id::text AS experiment_id, j.job_id::text AS job_id FROM e, j`;

export const SUGGESTION_INSERT_SQL = `
WITH capacity AS (
  SELECT (SELECT COUNT(*) FROM suggestion_set WHERE status IN ('pending','running')) < ${MAX_ACTIVE} AS ok
), s AS (
  INSERT INTO suggestion_set(lottery_slug, strategy, seed, budget, ticket_count)
  SELECT $1::text, $2::text, $3::bigint, $4::numeric, $5::int FROM capacity WHERE ok
  RETURNING set_id
), j AS (
  INSERT INTO job(kind, lottery_slug, params)
  SELECT 'suggestion', $1::text, jsonb_build_object('set_id', set_id) FROM s
  RETURNING job_id
)
SELECT s.set_id::text AS suggestion_set_id, j.job_id::text AS job_id FROM s, j`;

export const EXPERIMENTS_LIST_SQL = `
SELECT e.experiment_id::text AS id, e.kind, e.lottery_slug, e.status, e.models, e.config, ${TS('e.created_at')} AS created_at, ${TS('e.started_at')} AS started_at,
       ${TS('e.completed_at')} AS completed_at, e.progress, e.conclusion->>'summary' AS verdict_summary, e.conclusion->>'verdict' AS verdict
  FROM experiment e
 WHERE ($1::text IS NULL OR e.lottery_slug = $1::text) AND ($2::text IS NULL OR e.kind = $2::text) AND ($3::text IS NULL OR e.status = $3::text)
 ORDER BY e.experiment_id DESC LIMIT $4::int`;

export const EXPERIMENT_SQL = `
SELECT e.experiment_id::text AS id, e.kind, e.lottery_slug, e.status, e.config, e.seed::text AS seed, e.models, e.train_cutoff_contest, e.test_start_contest, e.test_end_contest,
       e.n_hypotheses, e.code_version, e.data_fingerprint, e.error, e.progress, e.conclusion, ${TS('e.created_at')} AS created_at, ${TS('e.started_at')} AS started_at, ${TS('e.completed_at')} AS completed_at
  FROM experiment e WHERE e.experiment_id = $1::bigint`;

export const EXPERIMENT_RESULTS_SQL = `
SELECT model_name, metric_name, value, ci_low, ci_high, baseline_value, baseline_ci_low, baseline_ci_high, p_value, q_value, verdict, payload
  FROM experiment_result WHERE experiment_id = $1::bigint ORDER BY model_name, metric_name`;

export const SUGGESTIONS_LIST_SQL = `
SELECT s.set_id::text AS id, s.lottery_slug, s.strategy, s.status, s.ticket_count, s.budget::text AS budget, ${TS('s.created_at')} AS created_at
  FROM suggestion_set s WHERE ($1::text IS NULL OR s.lottery_slug = $1::text) ORDER BY s.set_id DESC LIMIT $2::int`;

export const SUGGESTION_SQL = `
SELECT s.set_id::text AS id, s.lottery_slug, s.strategy, s.seed::text AS seed, s.status, s.budget::text AS budget, s.ticket_count, s.based_on_contest, ${TS('s.created_at')} AS created_at,
       s.explanation, s.evidence, s.total_cost::text AS total_cost, s.error
  FROM suggestion_set s WHERE s.set_id = $1::bigint`;

export const SUGGESTION_TICKETS_SQL = `
SELECT position, numbers, heuristic_score, score_interpretation, jackpot_numerator::text AS jackpot_numerator, jackpot_denominator::text AS jackpot_denominator, cost::text AS cost
  FROM suggestion WHERE set_id = $1::bigint ORDER BY position`;

export const LOTTERY_PRICE_SQL = `SELECT simple_price::text AS simple_price FROM lottery_type WHERE slug = $1`;

const newSeed = () => randomInt(1, 2 ** 31 - 1);
const idParam = { type: 'object', required: ['id'], properties: { id: { type: 'integer', minimum: 1, maximum: 2_000_000_000 } } } as const;
const limitSchema = { type: 'integer', minimum: 1, maximum: MAX_LIMIT, default: 20 } as const;

type BacktestBody = {
  kind: 'backtest';
  lottery: string;
  models?: string[];
  test_contests?: number;
  tickets_per_contest?: number;
  seeds?: number;
  baseline_replicates?: number;
  refit_every?: number;
  seed?: number;
};
type MonteBody = { kind: 'montecarlo'; lottery: string; tickets_per_contest: number; contests: number; replicates: number; seed?: number };

const experimentProps = {
  kind: { type: 'string', enum: ['backtest', 'montecarlo'] },
  lottery: lotteryEnum,
  models: { type: 'array', minItems: 1, maxItems: 8, uniqueItems: true, items: { type: 'string', enum: MODEL_NAMES } },
  test_contests: { type: 'integer', minimum: 50, maximum: 2000 },
  tickets_per_contest: { type: 'integer', minimum: 1, maximum: 100 },
  seeds: { type: 'integer', minimum: 1, maximum: 10 },
  baseline_replicates: { type: 'integer', minimum: 50, maximum: 2000 },
  refit_every: { type: 'integer', minimum: 10, maximum: 500 },
  contests: { type: 'integer', minimum: 1, maximum: 5000 },
  replicates: { type: 'integer', minimum: 10, maximum: 2000 },
  seed: { type: 'integer', minimum: 0, maximum: 2_147_483_647 },
} as const;
const BACKTEST_KEYS = ['kind', 'lottery', 'models', 'test_contests', 'tickets_per_contest', 'seeds', 'baseline_replicates', 'refit_every', 'seed'];
const MONTE_KEYS = ['kind', 'lottery', 'tickets_per_contest', 'contests', 'replicates', 'seed'];
const experimentBodySchema = { type: 'object', required: ['kind', 'lottery'], properties: experimentProps } as const;

function requireHeader(request: { headers: Record<string, unknown> }, reply: { code(c: number): { send(b: unknown): unknown } }) {
  if (request.headers['x-requested-with'] !== 'cassino') {
    return reply.code(403).send({ error: 'Cabeçalho X-Requested-With: cassino obrigatório' });
  }
  return null;
}

export async function registerExperimentRoutes(app: FastifyInstance, db: Queryable): Promise<void> {
  app.get('/api/models', async () => ({ items: MODELS }));

  app.post<{ Body: BacktestBody | MonteBody }>('/api/experiments', { schema: { body: experimentBodySchema } }, async (request, reply) => {
    const denied = requireHeader(request, reply);
    if (denied) return denied;
    const b = request.body;
    // O validador remove chaves desconhecidas silenciosamente: confira pelo corpo cru aceito por tipo.
    const allowed = b.kind === 'backtest' ? BACKTEST_KEYS : MONTE_KEYS;
    const sent = Object.keys(b);
    if (sent.some((key) => !allowed.includes(key))) return reply.code(400).send({ error: `Parâmetro não aceito para ${b.kind}` });
    if (b.kind === 'montecarlo' && (b.tickets_per_contest === undefined || b.contests === undefined || b.replicates === undefined)) {
      return reply.code(400).send({ error: 'montecarlo requer tickets_per_contest, contests e replicates' });
    }
    if (b.kind === 'backtest' && (b.tickets_per_contest ?? 10) > 50) return reply.code(400).send({ error: 'backtest aceita no máximo 50 bilhetes por concurso' });
    let config: Record<string, unknown>;
    let models: string[];
    if (b.kind === 'backtest') {
      const test_contests = b.test_contests ?? 500;
      const tickets = b.tickets_per_contest ?? 10;
      if (test_contests * tickets > 25_000) return reply.code(400).send({ error: 'test_contests × tickets_per_contest não pode exceder 25000 (limite de CPU/memória)' });
      models = b.models ?? MODELS.filter((m) => m.default && m.name !== 'uniform_baseline').map((m) => m.name);
      config = {
        models,
        test_contests,
        tickets_per_contest: tickets,
        seeds: b.seeds ?? 5,
        baseline_replicates: b.baseline_replicates ?? 500,
        refit_every: b.refit_every ?? 50,
      };
    } else {
      models = ['montecarlo'];
      config = { tickets_per_contest: b.tickets_per_contest, contests: b.contests, replicates: b.replicates };
    }
    const seed = b.seed ?? newSeed();
    const { rows } = await db.query(EXPERIMENT_INSERT_SQL, [b.kind, b.lottery, JSON.stringify(config), seed, models]);
    if (rows.length === 0) return reply.code(429).send({ error: `Já existem ${MAX_ACTIVE} experimentos pendentes ou em execução; aguarde a conclusão` });
    return reply.code(202).send({ experiment_id: rows[0].experiment_id, job_id: rows[0].job_id, seed });
  });

  app.get<{ Querystring: { lottery?: string; kind?: string; status?: string; limit: number } }>(
    '/api/experiments',
    {
      schema: {
        querystring: {
          type: 'object',
          properties: {
            lottery: lotteryEnum,
            kind: { type: 'string', enum: ['backtest', 'montecarlo'] },
            status: { type: 'string', enum: ['pending', 'running', 'succeeded', 'failed'] },
            limit: limitSchema,
          },
        },
      },
      preValidation: rejectUnknownQuery(['lottery', 'kind', 'status', 'limit']),
    },
    async (request) => {
      const q = request.query;
      const { rows } = await db.query(EXPERIMENTS_LIST_SQL, [q.lottery ?? null, q.kind ?? null, q.status ?? null, q.limit]);
      return { items: rows };
    },
  );

  app.get<{ Params: { id: number } }>('/api/experiments/:id', { schema: { params: idParam } }, async (request, reply) => {
    const exp = (await db.query(EXPERIMENT_SQL, [request.params.id])).rows[0];
    if (!exp) return notFound(reply, 'Experimento não encontrado');
    const results = (await db.query(EXPERIMENT_RESULTS_SQL, [request.params.id])).rows;
    const { conclusion, ...experiment } = exp;
    return {
      experiment,
      results,
      conclusion: conclusion
        ? { summary: conclusion.summary ?? '', verdict: conclusion.verdict ?? 'inconclusive', limitations: conclusion.limitations ?? [], ...conclusion }
        : null,
      disclaimer: DISCLAIMER,
    };
  });

  app.post<{ Body: { lottery: string; strategy: (typeof STRATEGIES)[number]; tickets?: number; budget?: number; seed?: number } }>(
    '/api/suggestions',
    {
      schema: {
        body: {
          type: 'object',
          additionalProperties: false,
          required: ['lottery', 'strategy'],
          properties: {
            lottery: lotteryEnum,
            strategy: { type: 'string', enum: [...STRATEGIES] },
            tickets: { type: 'integer', minimum: 1, maximum: 200 },
            budget: { type: 'number', minimum: 0, maximum: 100_000 },
            seed: { type: 'integer', minimum: 0, maximum: 2_147_483_647 },
          },
        },
      },
    },
    async (request, reply) => {
      const denied = requireHeader(request, reply);
      if (denied) return denied;
      const b = request.body;
      if (b.tickets !== undefined && b.budget !== undefined) return reply.code(400).send({ error: 'Informe tickets ou budget, não ambos' });
      const price = Number((await db.query(LOTTERY_PRICE_SQL, [b.lottery])).rows[0]?.simple_price);
      if (!Number.isFinite(price)) return notFound(reply, 'Modalidade não encontrada');
      const count = b.tickets ?? (b.budget !== undefined ? Math.floor(b.budget / price) : 1);
      if (count < 1) return reply.code(400).send({ error: `Orçamento insuficiente para um bilhete (R$ ${price.toFixed(2)})` });
      if (count > 200) return reply.code(400).send({ error: 'No máximo 200 bilhetes por conjunto' });
      const { rows } = await db.query(SUGGESTION_INSERT_SQL, [b.lottery, b.strategy, b.seed ?? newSeed(), b.budget ?? null, count]);
      if (rows.length === 0) return reply.code(429).send({ error: 'Muitos conjuntos em processamento; aguarde' });
      return reply.code(202).send({ suggestion_set_id: rows[0].suggestion_set_id, job_id: rows[0].job_id, ticket_count: count });
    },
  );

  app.get<{ Querystring: { lottery?: string; limit: number } }>(
    '/api/suggestions',
    { schema: { querystring: { type: 'object', properties: { lottery: lotteryEnum, limit: limitSchema } } }, preValidation: rejectUnknownQuery(['lottery', 'limit']) },
    async (request) => ({ items: (await db.query(SUGGESTIONS_LIST_SQL, [request.query.lottery ?? null, request.query.limit])).rows }),
  );

  app.get<{ Params: { id: number } }>('/api/suggestions/:id', { schema: { params: idParam } }, async (request, reply) => {
    const set = (await db.query(SUGGESTION_SQL, [request.params.id])).rows[0];
    if (!set) return notFound(reply, 'Conjunto não encontrado');
    const tickets = (await db.query(SUGGESTION_TICKETS_SQL, [request.params.id])).rows.map((t: any) => ({
      position: t.position,
      numbers: t.numbers,
      heuristic_score: t.heuristic_score,
      score_interpretation: t.score_interpretation,
      exact_jackpot_probability: { numerator: t.jackpot_numerator, denominator: t.jackpot_denominator },
      cost: t.cost,
    }));
    const first = tickets[0];
    const jackpot = first
      ? {
          event: 'pelo menos um bilhete com o prêmio máximo em um único concurso (bilhetes simples distintos)',
          numerator: String(set.ticket_count),
          denominator: first.exact_jackpot_probability.denominator,
          probability: Number(set.ticket_count) / Number(first.exact_jackpot_probability.denominator),
        }
      : null;
    return { set: { ...set, jackpot_probability: jackpot }, tickets, predictive_advantage_validated: false, illustrative_only: true, disclaimer: DISCLAIMER };
  });
}
