// Fixtures LOCAIS apenas para teste (não são dados reais nem usadas em produção).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { ProbabilitiesPage } from './Probabilities';
import { ModelsPage } from './Models';
import { clearCache } from '../lib/useApi';

const FIXTURE_LOTTERIES = {
  items: [{ slug: 'megasena', name: 'Mega-Sena', pool_size: 60, draw_size: 6, min_bet_size: 6, max_bet_size: 20, simple_price: '6.00', price_source: 'fixture', price_checked_on: '2026-01-01', draw_count: 1, last_contest: 1, last_draw_date: '2026-01-01' }],
};
const FIXTURE_PROB = {
  lottery: 'megasena',
  bet_size: 6,
  draw_size: 6,
  pool_size: 60,
  total_combinations: '50063860',
  simple_games: '1',
  simple_price: '6.00',
  bet_cost: '6.00',
  price_source: 'fixture',
  formula_version: 'fixture-v1',
  tiers: [
    { hits: 6, is_prize_tier: true, exact: { numerator: '1', denominator: '50063860' }, probability: 1.9974489e-8, one_in: 50063860, at_least: { numerator: '1', denominator: '50063860' }, at_least_probability: 1.9974489e-8 },
    { hits: 5, is_prize_tier: true, exact: { numerator: '324', denominator: '50063860' }, probability: 6.4717e-6, one_in: 154518.08, at_least: { numerator: '325', denominator: '50063860' }, at_least_probability: 6.4917e-6 },
  ],
  tickets_jackpot: { count: 1, contests: 1, probability: 1.9974489e-8, one_in: 50063860 },
  assumptions: ['Sorteios independentes e uniformes (premissa de fixture).'],
};
const FIXTURE_EXPERIMENTS = {
  items: [{ id: '42', kind: 'backtest', lottery_slug: 'megasena', status: 'succeeded', models: ['uniform'], config: {}, created_at: '2026-11-20T10:00:00Z', started_at: null, completed_at: null, progress: null, verdict_summary: 'Sem evidência de vantagem' }],
};
const FIXTURE_DETAIL = {
  experiment: { id: '42', kind: 'backtest', lottery_slug: 'megasena', status: 'succeeded', config: {}, seed: 1, train_cutoff_contest: 2500, test_start_contest: 2501, test_end_contest: 3000, n_hypotheses: 4, code_version: 'fx', data_fingerprint: 'abcdef0123456789abcdef', error: null, progress: null, created_at: '2026-11-20T10:00:00Z', started_at: null, completed_at: null },
  results: [
    { model_name: 'frequency', metric_name: 'mean_hits_per_ticket', value: 0.099, ci_low: 0.09, ci_high: 0.108, baseline_value: 0.1, baseline_ci_low: 0.095, baseline_ci_high: 0.105, p_value: 0.8, q_value: 0.9, verdict: 'worse_than_baseline', payload: null },
  ],
  conclusion: { summary: 'Nenhum modelo superou o baseline.', verdict: 'no_evidence_of_advantage', limitations: ['Amostra finita (fixture).'] },
  disclaimer: 'fixture',
};

function route(map: Record<string, { status?: number; body: unknown }>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const key = Object.keys(map).find((k) => url.startsWith('/api' + k));
      const r = key ? map[key] : { status: 404, body: { message: 'Route not found', error: 'Not Found', statusCode: 404 } };
      return new Response(JSON.stringify(r?.body), { status: r?.status ?? 200 });
    }),
  );
}

afterEach(() => {
  cleanup();
  clearCache();
  vi.unstubAllGlobals();
});

describe('página Probabilidades', () => {
  it('mostra faixas, fração exata, premissas e o aviso de retorno', async () => {
    route({ '/lotteries': { body: FIXTURE_LOTTERIES }, '/probabilities': { body: FIXTURE_PROB } });
    render(<ProbabilitiesPage />);
    expect((await screen.findAllByText('1 em 50.063.860')).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('1 / 50.063.860').length).toBeGreaterThan(0);
    expect(screen.getByText(/premissa de fixture/)).toBeTruthy();
    expect(screen.getByText(/Chance de algum prêmio ≠ retorno positivo/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Calcular' })).toBeTruthy();
  });

  it('exibe erro do servidor sem inventar dados', async () => {
    route({ '/lotteries': { body: FIXTURE_LOTTERIES }, '/probabilities': { status: 400, body: { error: 'bet_size inválido' } } });
    render(<ProbabilitiesPage />);
    expect(await screen.findByText('bet_size inválido')).toBeTruthy();
  });
});

describe('página Experimentos (Modelos e backtests)', () => {
  it('lista experimentos e trata /api/models ausente como "ainda não disponível"', async () => {
    route({ '/models': { status: 404, body: { message: 'Route GET:/api/models not found', error: 'Not Found', statusCode: 404 } }, '/experiments': { body: FIXTURE_EXPERIMENTS } });
    render(<ModelsPage />);
    expect(await screen.findByText('Sem evidência de vantagem')).toBeTruthy();
    expect(screen.getAllByText('Ainda não disponível').length).toBeGreaterThan(0);
  });

  it('detalhe mostra veredito negativo com destaque, conclusão e limitações', async () => {
    route({ '/models': { body: { items: [] } }, '/experiments/42': { body: FIXTURE_DETAIL } });
    render(<ModelsPage experimentId="42" />);
    await waitFor(() => expect(screen.getByText(/Pior que o baseline/)).toBeTruthy());
    expect(screen.getByText('Nenhum modelo superou o baseline.')).toBeTruthy();
    expect(screen.getByText('Amostra finita (fixture).')).toBeTruthy();
    expect(screen.getByText('Sem evidência de vantagem')).toBeTruthy();
    expect(screen.getByRole('img', { name: /Modelo × baseline/ })).toBeTruthy();
  });
});
