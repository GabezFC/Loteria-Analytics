import type { FastifyInstance } from 'fastify';
import { LOTTERY_SLUGS, MAX_LIMIT, STATUS_SQL, notFound, rejectUnknownQuery, type Queryable } from './draws.js';

const lotteryEnum = { type: 'string', enum: [...LOTTERY_SLUGS] } as const;
const WINDOWS = ['30', '100', '300', '1000', 'all'] as const;
const DISCLAIMER =
  'Estatísticas descritivas do passado. Não são probabilidades de resultados futuros: sorteios justos são independentes e uniformes.';

// ---------------------------------------------------------------- ingestão / jobs / admin
export const RUNS_SQL = `
SELECT r.ingest_run_id::text AS id, r.lottery_slug, r.status, to_char(r.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS started_at,
       to_char(r.completed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS completed_at, r.row_count, r.inserted_count, r.unchanged_count,
       r.prize_changed_count, r.divergent_count, r.quarantined_count, r.checkpoint_contest, r.adapter_version, r.source_sha256, r.error_message
  FROM ingest_run r ORDER BY r.ingest_run_id DESC LIMIT $1::int`;

export const DIVERGENCES_SQL = `
SELECT v.divergence_id::text AS id, d.lottery_slug, d.contest, v.status, v.previous_value, v.current_value,
       to_char(v.detected_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS detected_at, v.resolution_note
  FROM ingest_divergence v JOIN lottery_draw d USING (draw_id)
 WHERE ($1::text IS NULL OR v.status = $1::text) ORDER BY v.divergence_id DESC LIMIT $2::int`;

export const QUARANTINE_SQL = `
SELECT q.quarantine_id::text AS id, q.lottery_slug, q.contest, q.kind, q.reason, q.source_line,
       to_char(q.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at
  FROM ingest_quarantine q ORDER BY q.quarantine_id DESC LIMIT $1::int`;

export const JOBS_SQL = `
SELECT j.job_id::text AS id, j.kind, j.lottery_slug, j.status, j.attempts, j.error, j.params,
       to_char(j.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at,
       to_char(j.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS started_at,
       to_char(j.finished_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS finished_at
  FROM job j WHERE ($1::text IS NULL OR j.kind = $1::text) AND ($2::text IS NULL OR j.status = $2::text)
 ORDER BY j.job_id DESC LIMIT $3::int`;

export const INGEST_JOB_SQL = `
INSERT INTO job(kind, lottery_slug) VALUES ('ingest', $1::text)
ON CONFLICT (kind, COALESCE(lottery_slug, ''), md5(params::text)) WHERE status = 'pending' DO NOTHING
RETURNING job_id::text AS id`;

export async function registerOpsRoutes(app: FastifyInstance, db: Queryable): Promise<void> {
  const limitSchema = { type: 'integer', minimum: 1, maximum: MAX_LIMIT, default: 20 } as const;

  app.get('/api/ingestion/status', async () => {
    const { rows } = await db.query(STATUS_SQL);
    return { lotteries: rows };
  });

  app.get<{ Querystring: { limit: number } }>(
    '/api/ingestion/runs',
    { schema: { querystring: { type: 'object', properties: { limit: limitSchema } } }, preValidation: rejectUnknownQuery(['limit']) },
    async (request) => ({ items: (await db.query(RUNS_SQL, [request.query.limit])).rows }),
  );

  app.get<{ Querystring: { status?: string; limit: number } }>(
    '/api/ingestion/divergences',
    {
      schema: { querystring: { type: 'object', properties: { status: { type: 'string', enum: ['open', 'accepted', 'rejected'] }, limit: limitSchema } } },
      preValidation: rejectUnknownQuery(['status', 'limit']),
    },
    async (request) => ({ items: (await db.query(DIVERGENCES_SQL, [request.query.status ?? null, request.query.limit])).rows }),
  );

  app.get<{ Querystring: { limit: number } }>(
    '/api/ingestion/quarantine',
    { schema: { querystring: { type: 'object', properties: { limit: limitSchema } } }, preValidation: rejectUnknownQuery(['limit']) },
    async (request) => ({ items: (await db.query(QUARANTINE_SQL, [request.query.limit])).rows }),
  );

  app.get<{ Querystring: { kind?: string; status?: string; limit: number } }>(
    '/api/jobs',
    {
      schema: {
        querystring: {
          type: 'object',
          properties: {
            kind: { type: 'string', pattern: '^[a-z_]{1,40}$' },
            status: { type: 'string', enum: ['pending', 'running', 'succeeded', 'failed'] },
            limit: limitSchema,
          },
        },
      },
      preValidation: rejectUnknownQuery(['kind', 'status', 'limit']),
    },
    async (request) => ({ items: (await db.query(JOBS_SQL, [request.query.kind ?? null, request.query.status ?? null, request.query.limit])).rows }),
  );

  // Disparo manual da coleta. Só via Nginx em 127.0.0.1; exige cabeçalho próprio (bloqueia POST cross-site simples)
  // e aceita no máximo um job de ingestão pendente por escopo.
  const recent: number[] = [];
  app.post<{ Body: { lottery?: string } }>(
    '/api/admin/ingestion',
    {
      schema: { body: { type: 'object', additionalProperties: false, properties: { lottery: lotteryEnum } } },
    },
    async (request, reply) => {
      if (request.headers['x-requested-with'] !== 'cassino') return reply.code(403).send({ error: 'Cabeçalho X-Requested-With: cassino obrigatório' });
      const now = Date.now();
      while (recent.length && now - (recent[0] as number) > 60_000) recent.shift();
      if (recent.length >= 6) return reply.code(429).send({ error: 'Muitas solicitações; aguarde um minuto' });
      recent.push(now);
      const { rows } = await db.query(INGEST_JOB_SQL, [request.body?.lottery ?? null]);
      if (rows.length === 0) return reply.code(409).send({ error: 'Já existe uma coleta pendente para este escopo' });
      return reply.code(202).send({ job_id: rows[0].id, status: 'pending' });
    },
  );
}

// ---------------------------------------------------------------- probabilidades exatas
export const PROB_TYPE_SQL = `SELECT slug, pool_size, draw_size, min_bet_size, max_bet_size, simple_price::text AS simple_price, price_source FROM lottery_type WHERE slug = $1`;
export const PROB_ROWS_SQL = `
SELECT hits, is_prize_tier, exact_numerator::text AS exact_numerator, exact_denominator::text AS exact_denominator, at_least_numerator::text AS at_least_numerator,
       probability, at_least_probability, simple_games::text AS simple_games, cost::text AS cost, formula_version
  FROM probability_table WHERE lottery_slug = $1 AND bet_size = $2 ORDER BY hits DESC`;

interface ProbQuery {
  lottery: (typeof LOTTERY_SLUGS)[number];
  bet_size?: number;
  hits?: number;
  tickets?: number;
  contests: number;
  budget?: number;
}

export async function registerProbabilityRoutes(app: FastifyInstance, db: Queryable): Promise<void> {
  const props = {
    lottery: lotteryEnum,
    bet_size: { type: 'integer', minimum: 1, maximum: 100 },
    hits: { type: 'integer', minimum: 0, maximum: 20 },
    tickets: { type: 'integer', minimum: 1, maximum: 100_000_000 },
    contests: { type: 'integer', minimum: 1, maximum: 10_000, default: 1 },
    budget: { type: 'number', minimum: 0, maximum: 1_000_000_000 },
  } as const;
  app.get<{ Querystring: ProbQuery }>(
    '/api/probabilities',
    { schema: { querystring: { type: 'object', required: ['lottery'], properties: props } }, preValidation: rejectUnknownQuery(Object.keys(props)) },
    async (request, reply) => {
      const q = request.query;
      const t = (await db.query(PROB_TYPE_SQL, [q.lottery])).rows[0];
      if (!t) return notFound(reply, 'Modalidade não encontrada');
      const betSize = q.bet_size ?? t.min_bet_size;
      if (betSize < t.min_bet_size || betSize > t.max_bet_size) {
        return reply.code(400).send({ error: `bet_size deve estar entre ${t.min_bet_size} e ${t.max_bet_size} para ${q.lottery}` });
      }
      if ((q.tickets !== undefined || q.budget !== undefined) && betSize !== t.draw_size) {
        return reply.code(400).send({ error: 'tickets/budget aplicam-se apenas a apostas simples (bet_size = dezenas sorteadas); apostas múltiplas exigem análise de cobertura combinatória' });
      }
      if (q.tickets !== undefined && q.budget !== undefined) return reply.code(400).send({ error: 'Informe tickets ou budget, não ambos' });
      const rows = (await db.query(PROB_ROWS_SQL, [q.lottery, betSize])).rows;
      if (rows.length === 0) return reply.code(503).send({ error: 'Tabela de probabilidades ainda não calculada; aguarde o analisador' });
      const total = BigInt(rows[0].exact_denominator);
      const simpleGames = BigInt(rows[0].simple_games);
      const oneIn = (p: number) => (p > 0 ? 1 / p : null);
      let tiers = rows.map((r: any) => ({
        hits: r.hits,
        is_prize_tier: r.is_prize_tier,
        exact: { numerator: r.exact_numerator, denominator: r.exact_denominator },
        probability: r.probability,
        one_in: oneIn(r.probability),
        at_least: { numerator: r.at_least_numerator, denominator: r.exact_denominator },
        at_least_probability: r.at_least_probability,
      }));
      if (q.hits !== undefined) {
        tiers = tiers.filter((x: any) => x.hits === q.hits);
        if (tiers.length === 0) return reply.code(400).send({ error: `hits deve estar entre 0 e ${t.draw_size}` });
      }
      const maxTickets = total; // bilhetes simples distintos possíveis
      let tickets: { count: string; contests: number; probability: number; one_in: number | null; fraction?: { numerator: string; denominator: string }; budget?: number; spent?: string } | undefined;
      if (q.tickets !== undefined || q.budget !== undefined) {
        const unit = Number(t.simple_price);
        let m = q.tickets !== undefined ? BigInt(q.tickets) : BigInt(Math.floor((q.budget as number) / unit));
        if (m > maxTickets) {
          if (q.tickets !== undefined) return reply.code(400).send({ error: `tickets excede C(N,k) = ${total} bilhetes distintos` });
          m = maxTickets;
        }
        const per = Number(m) / Number(total);
        const p = q.contests === 1 ? per : -Math.expm1(q.contests * Math.log1p(-per));
        tickets = {
          count: m.toString(),
          contests: q.contests,
          probability: p,
          one_in: oneIn(p),
          ...(q.contests === 1 ? { fraction: { numerator: m.toString(), denominator: total.toString() } } : {}),
          ...(q.budget !== undefined ? { budget: q.budget, spent: (Number(m) * unit).toFixed(2) } : {}),
        };
      }
      return {
        lottery: q.lottery,
        bet_size: betSize,
        draw_size: t.draw_size,
        pool_size: t.pool_size,
        total_combinations: total.toString(),
        simple_games: simpleGames.toString(),
        simple_price: t.simple_price,
        bet_cost: rows[0].cost,
        price_source: t.price_source,
        formula_version: rows[0].formula_version,
        tiers,
        tickets_jackpot: tickets ?? null,
        assumptions: [
          'Sorteio uniforme de k dezenas distintas entre N; concursos independentes.',
          'hits = quantidade de dezenas sorteadas contidas na aposta; P(X=r) = C(b,r)·C(N-b,k-r)/C(N,k).',
          'tickets: m apostas simples DISTINTAS no mesmo concurso (P = m/C(N,k)); para c concursos, 1-(1-m/C(N,k))^c.',
          'O histórico de resultados não altera estas probabilidades. Chance de algum prêmio não é chance de retorno financeiro positivo.',
          'Preços são parâmetros editáveis em lottery_type e devem ser confirmados na CAIXA.',
        ],
      };
    },
  );
}

// ---------------------------------------------------------------- estatísticas
export const RUN_SQL = `
SELECT analysis_run_id::text AS id, lottery_slug, method, window_label, window_size, window_start_contest, window_end_contest, sample_size, code_version, seed,
       to_char(completed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS completed_at, params
  FROM analysis_run WHERE lottery_slug = $1 AND method = 'statistics' AND window_label = $2 AND status = 'succeeded'
 ORDER BY window_end_contest DESC, analysis_run_id DESC LIMIT 1`;
export const NUMBERS_SQL = `
SELECT number, frequency, relative_frequency, expected_frequency, z_score, ci_low, ci_high, current_delay, max_delay, mean_gap
  FROM number_stat WHERE analysis_run_id = $1::bigint ORDER BY number`;
export const RESULTS_SQL = `SELECT kind, payload FROM analysis_result WHERE analysis_run_id = $1::bigint AND kind = ANY($2::text[])`;
export const COMBOS_SQL = `
SELECT combo_size, numbers, observed, expected, lift, z_score, p_value, q_value, sample_size
  FROM combination_stat WHERE analysis_run_id = $1::bigint AND combo_size = $2::int
 ORDER BY CASE WHEN $3::text = 'under' THEN z_score END ASC, CASE WHEN $3::text <> 'under' THEN z_score END DESC LIMIT $4::int`;
export const WINDOWS_SQL = `
SELECT window_label, window_start_contest, window_end_contest, sample_size,
       to_char(completed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS completed_at
  FROM analysis_run r WHERE lottery_slug = $1 AND method = 'statistics' AND status = 'succeeded'
   AND analysis_run_id = (SELECT analysis_run_id FROM analysis_run x WHERE x.lottery_slug = r.lottery_slug AND x.method = r.method AND x.window_label = r.window_label AND x.status = 'succeeded' ORDER BY window_end_contest DESC, analysis_run_id DESC LIMIT 1)
 ORDER BY window_size NULLS LAST`;

export async function registerStatsRoutes(app: FastifyInstance, db: Queryable): Promise<void> {
  const base = { lottery: lotteryEnum, window: { type: 'string', enum: [...WINDOWS], default: 'all' } } as const;
  const noRun = (reply: any) =>
    notFound(reply, 'Análise ainda não disponível para esta modalidade/janela (aguarde o analisador ou verifique /api/jobs)');

  app.get<{ Querystring: { lottery: string; window: string } }>(
    '/api/stats',
    { schema: { querystring: { type: 'object', required: ['lottery'], properties: base } }, preValidation: rejectUnknownQuery(['lottery', 'window']) },
    async (request, reply) => {
      const run = (await db.query(RUN_SQL, [request.query.lottery, request.query.window])).rows[0];
      if (!run) return noRun(reply);
      const numbers = (await db.query(NUMBERS_SQL, [run.id])).rows;
      const results = Object.fromEntries((await db.query(RESULTS_SQL, [run.id, ['distributions', 'meta']])).rows.map((r: any) => [r.kind, r.payload]));
      return { analysis_run: run, numbers, distributions: results.distributions ?? null, meta: results.meta ?? null, disclaimer: DISCLAIMER };
    },
  );

  app.get<{ Querystring: { lottery: string; window: string } }>(
    '/api/stats/inference',
    { schema: { querystring: { type: 'object', required: ['lottery'], properties: base } }, preValidation: rejectUnknownQuery(['lottery', 'window']) },
    async (request, reply) => {
      const run = (await db.query(RUN_SQL, [request.query.lottery, request.query.window])).rows[0];
      if (!run) return noRun(reply);
      const results = Object.fromEntries((await db.query(RESULTS_SQL, [run.id, ['inference', 'meta']])).rows.map((r: any) => [r.kind, r.payload]));
      return { analysis_run: run, inference: results.inference ?? null, available: Boolean(results.inference), disclaimer: DISCLAIMER };
    },
  );

  app.get<{ Querystring: { lottery: string; window: string; size: number; order: string; limit: number } }>(
    '/api/stats/combinations',
    {
      schema: {
        querystring: {
          type: 'object',
          required: ['lottery'],
          properties: {
            ...base,
            size: { type: 'integer', enum: [2, 3, 4], default: 2 },
            order: { type: 'string', enum: ['over', 'under'], default: 'over' },
            limit: { type: 'integer', minimum: 1, maximum: 100, default: 20 },
          },
        },
      },
      preValidation: rejectUnknownQuery(['lottery', 'window', 'size', 'order', 'limit']),
    },
    async (request, reply) => {
      const q = request.query;
      const run = (await db.query(RUN_SQL, [q.lottery, q.window])).rows[0];
      if (!run) return noRun(reply);
      const items = (await db.query(COMBOS_SQL, [run.id, q.size, q.order, q.limit])).rows;
      const meta = (await db.query(RESULTS_SQL, [run.id, ['combination_meta']])).rows[0]?.payload ?? null;
      return {
        analysis_run: run,
        size: q.size,
        order: q.order,
        items,
        meta,
        note: 'z/p/q medem desvio da coocorrência esperada ao acaso no passado (q = correção Benjamini–Hochberg). Não indicam combinações mais prováveis no futuro.',
        disclaimer: DISCLAIMER,
      };
    },
  );

  app.get<{ Querystring: { lottery: string } }>(
    '/api/stats/windows',
    { schema: { querystring: { type: 'object', required: ['lottery'], properties: { lottery: lotteryEnum } } }, preValidation: rejectUnknownQuery(['lottery']) },
    async (request) => ({ items: (await db.query(WINDOWS_SQL, [request.query.lottery])).rows }),
  );
}
