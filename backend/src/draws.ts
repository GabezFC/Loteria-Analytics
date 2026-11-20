import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';

/** Contrato mínimo de acesso ao banco; satisfeito por pg.Pool e por dublês de teste. */
export interface Queryable {
  query(text: string, values?: unknown[]): Promise<{ rows: any[] }>;
}

export const LOTTERY_SLUGS = ['megasena', 'lotofacil', 'quina'] as const;
export type LotterySlug = (typeof LOTTERY_SLUGS)[number];
export const DEFAULT_LIMIT = 20;
export const MAX_LIMIT = 100;
export const MAX_OFFSET = 1_000_000;

/** O validador padrão do Fastify remove chaves desconhecidas; esta preValidation as rejeita com 400. */
export function rejectUnknownQuery(allowed: readonly string[]) {
  return async (request: FastifyRequest, reply: FastifyReply) => {
    const query = (request.query ?? {}) as Record<string, unknown>;
    if (Object.keys(query).some((key) => !allowed.includes(key))) {
      return reply.code(400).send({ error: 'Parâmetro de consulta desconhecido' });
    }
  };
}

export function notFound(reply: FastifyReply, message: string) {
  return reply.code(404).send({ error: message });
}

// Esquema real: lottery_draw(draw_id, lottery_slug, contest, draw_date) e draw_number(draw_id, number).
export const DRAWS_SQL = `
SELECT d.draw_id::text AS id,
       d.lottery_slug,
       d.contest,
       to_char(d.draw_date, 'YYYY-MM-DD') AS draw_date,
       COALESCE(
         (SELECT array_agg(n.number ORDER BY n.number)
            FROM draw_number n
           WHERE n.draw_id = d.draw_id),
         ARRAY[]::smallint[]
       ) AS numbers,
       COUNT(*) OVER()::int AS total
  FROM lottery_draw d
 WHERE ($1::text IS NULL OR d.lottery_slug = $1::text)
   AND ($4::int IS NULL OR d.contest = $4::int)
   AND ($5::date IS NULL OR d.draw_date >= $5::date)
   AND ($6::date IS NULL OR d.draw_date <= $6::date)
   AND ($7::int[] IS NULL OR (SELECT COUNT(*) FROM draw_number n WHERE n.draw_id = d.draw_id AND n.number = ANY($7::int[])) = cardinality($7::int[]))
 ORDER BY d.draw_date DESC, d.contest DESC, d.lottery_slug
 LIMIT $2::int OFFSET $3::int`;

export const STATUS_SQL = `
SELECT t.slug AS lottery_slug,
       t.name,
       COUNT(d.draw_id)::int AS draw_count,
       MIN(d.contest) AS first_contest,
       MAX(d.contest) AS last_contest,
       to_char(MAX(d.draw_date), 'YYYY-MM-DD') AS last_draw_date,
       (SELECT COUNT(*)::int FROM draw_gap g WHERE g.lottery_slug = t.slug) AS gap_count,
       (SELECT COUNT(*)::int FROM ingest_divergence v JOIN lottery_draw x USING (draw_id) WHERE x.lottery_slug = t.slug AND v.status = 'open') AS open_divergences,
       (SELECT COUNT(*)::int FROM ingest_quarantine q WHERE q.lottery_slug = t.slug) AS quarantined_rows,
       (SELECT COUNT(*)::int FROM draw_prize_tier p JOIN lottery_draw x USING (draw_id) WHERE x.lottery_slug = t.slug) AS prize_tier_rows,
       (SELECT to_jsonb(c) - 'lottery_slug' FROM collector_status c WHERE c.lottery_slug = t.slug) AS collector
  FROM lottery_type t
  LEFT JOIN lottery_draw d ON d.lottery_slug = t.slug
 GROUP BY t.slug, t.name
 ORDER BY t.slug`;

export const DRAW_DETAIL_SQL = `
SELECT d.draw_id::text AS id, d.lottery_slug, d.contest, to_char(d.draw_date, 'YYYY-MM-DD') AS draw_date,
       (SELECT array_agg(n.number ORDER BY n.number) FROM draw_number n WHERE n.draw_id = d.draw_id) AS numbers,
       COALESCE((SELECT jsonb_agg(jsonb_build_object('hits', t.hits, 'winners', t.winners, 'payout_amount', t.payout_amount::text) ORDER BY t.hits DESC)
                   FROM draw_prize_tier t WHERE t.draw_id = d.draw_id), '[]'::jsonb) AS prizes,
       (SELECT jsonb_build_object('winner_locations', e.winner_locations, 'accumulated_main', e.accumulated_main::text, 'total_collected', e.total_collected::text,
                                  'next_estimate', e.next_estimate::text, 'special_accumulated', e.special_accumulated::text, 'observation', e.observation)
          FROM draw_extra e WHERE e.draw_id = d.draw_id) AS extra,
       d.source_sha256 AS source_sha256, d.ingest_run_id
  FROM lottery_draw d WHERE d.lottery_slug = $1 AND d.contest = $2::int`;

export const LOTTERIES_SQL = `
SELECT t.slug, t.name, t.pool_size, t.draw_size, t.min_bet_size, t.max_bet_size, t.simple_price::text AS simple_price,
       t.price_source, to_char(t.price_checked_on, 'YYYY-MM-DD') AS price_checked_on,
       COUNT(d.draw_id)::int AS draw_count, MAX(d.contest) AS last_contest, to_char(MAX(d.draw_date), 'YYYY-MM-DD') AS last_draw_date
  FROM lottery_type t LEFT JOIN lottery_draw d ON d.lottery_slug = t.slug
 GROUP BY t.slug ORDER BY t.slug`;

const drawsQuerySchema = {
  type: 'object',
  additionalProperties: false,
  properties: {
    lottery: { type: 'string', enum: [...LOTTERY_SLUGS] },
    limit: { type: 'integer', minimum: 1, maximum: MAX_LIMIT, default: DEFAULT_LIMIT },
    offset: { type: 'integer', minimum: 0, maximum: MAX_OFFSET, default: 0 },
    contest: { type: 'integer', minimum: 1, maximum: 10_000_000 },
    date_from: { type: 'string', format: 'date' },
    date_to: { type: 'string', format: 'date' },
    numbers: { type: 'string', pattern: '^[0-9]{1,2}(,[0-9]{1,2}){0,19}$' },
  },
} as const;

interface DrawsQuery {
  lottery?: LotterySlug;
  limit: number;
  offset: number;
  contest?: number;
  date_from?: string;
  date_to?: string;
  numbers?: string;
}

export async function registerDrawRoutes(app: FastifyInstance, db: Queryable): Promise<void> {
  app.get('/api/lotteries', async () => {
    const { rows } = await db.query(LOTTERIES_SQL);
    return { items: rows };
  });

  app.get<{ Querystring: DrawsQuery }>(
    '/api/draws',
    {
      schema: { querystring: drawsQuerySchema },
      preValidation: rejectUnknownQuery(Object.keys(drawsQuerySchema.properties)),
    },
    async (request, reply) => {
      const { lottery = null, limit, offset, contest = null, date_from = null, date_to = null, numbers } = request.query;
      let wanted: number[] | null = null;
      if (numbers) {
        wanted = [...new Set(numbers.split(',').map(Number))];
        if (wanted.some((n) => n < 1 || n > 80)) return reply.code(400).send({ error: 'numbers: dezenas devem estar entre 1 e 80' });
      }
      const { rows } = await db.query(DRAWS_SQL, [lottery, limit, offset, contest, date_from, date_to, wanted]);
      const total = rows[0]?.total ?? 0;
      return { limit, offset, count: rows.length, total, items: rows.map(({ total: _t, ...rest }) => rest) };
    },
  );

  app.get<{ Params: { lottery: string; contest: number } }>(
    '/api/draws/:lottery/:contest',
    {
      schema: {
        params: {
          type: 'object',
          properties: { lottery: { type: 'string', enum: [...LOTTERY_SLUGS] }, contest: { type: 'integer', minimum: 1, maximum: 10_000_000 } },
          required: ['lottery', 'contest'],
        },
      },
    },
    async (request, reply) => {
      const { rows } = await db.query(DRAW_DETAIL_SQL, [request.params.lottery, request.params.contest]);
      if (rows.length === 0) return notFound(reply, 'Concurso não encontrado');
      return rows[0];
    },
  );
}
