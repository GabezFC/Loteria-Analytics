import Fastify from 'fastify';
import { afterEach, describe, expect, it } from 'vitest';
import { registerOpsRoutes } from '../src/api.js';
import { DEFAULT_LIMIT, DRAWS_SQL, STATUS_SQL, registerDrawRoutes, type Queryable } from '../src/draws.js';

type Call = { text: string; values?: unknown[] };

function fakeDb(rows: any[] = []): Queryable & { calls: Call[] } {
  const calls: Call[] = [];
  return {
    calls,
    async query(text, values) {
      calls.push({ text, values });
      return { rows };
    },
  };
}

const apps: Array<ReturnType<typeof Fastify>> = [];

async function build(db: Queryable) {
  const app = Fastify();
  apps.push(app);
  await registerDrawRoutes(app, db);
  await registerOpsRoutes(app, db);
  await app.ready();
  return app;
}

afterEach(async () => {
  await Promise.all(apps.splice(0).map((a) => a.close()));
});

describe('GET /api/draws', () => {
  it('usa defaults e parâmetros posicionais sem filtro de loteria', async () => {
    const db = fakeDb([{ id: '1', lottery_slug: 'quina', contest: 10, draw_date: '2024-01-02', numbers: [1, 2, 3, 4, 5], total: 1 }]);
    const app = await build(db);
    const res = await app.inject({ method: 'GET', url: '/api/draws' });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ limit: DEFAULT_LIMIT, offset: 0, count: 1, total: 1 });
    expect(db.calls).toEqual([{ text: DRAWS_SQL, values: [null, DEFAULT_LIMIT, 0, null, null, null, null] }]);
  });

  it('repassa lottery, limit e offset como parâmetros', async () => {
    const db = fakeDb();
    const app = await build(db);
    const res = await app.inject({ method: 'GET', url: '/api/draws?lottery=megasena&limit=5&offset=10' });
    expect(res.statusCode).toBe(200);
    expect(db.calls[0]?.values).toEqual(['megasena', 5, 10, null, null, null, null]);
  });

  it('não interpola entrada do usuário no SQL', () => {
    expect(DRAWS_SQL).toContain('$1');
    expect(DRAWS_SQL).toContain('lottery_draw');
    expect(DRAWS_SQL).toContain('draw_number');
  });

  it.each([
    ['lottery inválida', '?lottery=loto'],
    ['injeção em lottery', "?lottery=quina'%20OR%201=1--"],
    ['limit zero', '?limit=0'],
    ['limit acima do máximo', '?limit=101'],
    ['limit não numérico', '?limit=abc'],
    ['offset negativo', '?offset=-1'],
    ['offset fracionário', '?offset=1.5'],
    ['parâmetro desconhecido', '?foo=1'],
    ['data inválida', '?date_from=2024-13-45'],
    ['numbers inválido', '?numbers=1,a'],
    ['dezena fora da faixa', '?numbers=99'],
  ])('rejeita %s com 400 sem consultar o banco', async (_nome, qs) => {
    const db = fakeDb();
    const app = await build(db);
    const res = await app.inject({ method: 'GET', url: `/api/draws${qs}` });
    expect(res.statusCode).toBe(400);
    expect(db.calls).toHaveLength(0);
  });
});

describe('GET /api/ingestion/status', () => {
  it('agrega lottery_type LEFT JOIN lottery_draw e devolve as linhas', async () => {
    const rows = [
      { lottery_slug: 'lotofacil', name: 'Lotofácil', draw_count: 0, first_contest: null, last_contest: null, last_draw_date: null },
      { lottery_slug: 'megasena', name: 'Mega-Sena', draw_count: 3, first_contest: 1, last_contest: 3, last_draw_date: '1996-03-30' },
    ];
    const db = fakeDb(rows);
    const app = await build(db);
    const res = await app.inject({ method: 'GET', url: '/api/ingestion/status' });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ lotteries: rows });
    expect(db.calls).toEqual([{ text: STATUS_SQL, values: undefined }]);
    expect(STATUS_SQL).toMatch(/FROM lottery_type t\s+LEFT JOIN lottery_draw d/);
  });
});
