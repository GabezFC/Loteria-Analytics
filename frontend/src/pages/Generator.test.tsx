import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import { GeneratorPage } from './Generator';
import { clearCache } from '../lib/useApi';

// Fixtures locais no formato de GET /api/suggestions/:id.
const modalities = [
  { slug: 'lotofacil', name: 'Lotofácil', size: 15, denominator: '3268760', fraction: '3.268.760', cost: '3.50', total: '17.50', costLabel: '3,50', totalLabel: '17,50' },
  { slug: 'megasena', name: 'Mega-Sena', size: 6, denominator: '50063860', fraction: '50.063.860', cost: '6.00', total: '30.00', costLabel: '6,00', totalLabel: '30,00' },
  { slug: 'quina', name: 'Quina', size: 5, denominator: '24040016', fraction: '24.040.016', cost: '3.00', total: '15.00', costLabel: '3,00', totalLabel: '15,00' },
];
const explanation = 'Frequência suavizada: não aumenta a chance de acerto em sorteios justos.';
const event = 'pelo menos um bilhete com o prêmio máximo em um único concurso';

function detail(m = modalities[0]) {
  return {
    set: {
      id: '3', lottery_slug: m.slug, strategy: 'frequency_weighted', status: 'succeeded', seed: '42',
      ticket_count: 5, total_cost: m.total, budget: null, based_on_contest: 100, created_at: '2026-01-01T10:00:00Z', error: null,
      explanation: { text: explanation, version: 'fixture-v1', seed: 42, based_on_contest: 100, strategy: 'frequency_weighted', evidence_note: null },
      evidence: { experiment_id: 2, model_name: 'freq_w100', verdict: 'indistinguishable' },
      jackpot_probability: { event, numerator: '5', denominator: m.denominator, probability: 5 / Number(m.denominator) },
    },
    tickets: Array.from({ length: 5 }, (_, i) => ({
      position: i + 1, numbers: Array.from({ length: m.size }, (_, j) => i + j + 1),
      heuristic_score: 0.125, score_interpretation: 'Peso médio das dezenas',
      exact_jackpot_probability: { numerator: '1', denominator: m.denominator }, cost: m.cost,
    })),
    predictive_advantage_validated: false, illustrative_only: true, disclaimer: 'Dados apenas ilustrativos (fixture).',
  };
}

function serve(body: unknown, status = 200) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === '/api/suggestions/3') return new Response(JSON.stringify(body), { status });
    if (url === '/api/suggestions?limit=10') return Response.json({ items: [] });
    throw new Error('URL inesperada: ' + url);
  }));
}

afterEach(() => {
  cleanup();
  clearCache();
  vi.unstubAllGlobals();
});

describe('detalhe do Gerador', () => {
  it.each(modalities)('renderiza a resposta realista de $name com os cinco bilhetes', async (m) => {
    const d = detail(m);
    serve(d);
    render(<GeneratorPage suggestionId="3" />);

    const heading = await screen.findByRole('heading', { name: `Conjunto #3 — ${m.name}` });
    const summary = within(heading.closest('section')!);
    expect(summary.getByText('Ponderada por frequência histórica')).toBeTruthy();
    expect(summary.getByText(explanation)).toBeTruthy();
    expect(summary.getByText('até o concurso 100')).toBeTruthy();
    expect(summary.getByText(/versão do gerador: fixture-v1/)).toBeTruthy();
    expect(summary.getByText(new RegExp(`R\\$\\s*${m.totalLabel}`))).toBeTruthy();
    expect(summary.getByText(new RegExp(`5 / ${m.fraction.replaceAll('.', '\\.')}`))).toBeTruthy();
    expect(summary.getByText('Indistinguível do baseline')).toBeTruthy();
    expect(summary.getByRole('link', { name: '#2' }).getAttribute('href')).toBe('#/modelos/2');

    const table = within(screen.getByRole('table', { name: 'Bilhetes sugeridos' }));
    expect(table.getByRole('columnheader', { name: 'Pontuação descritiva (NÃO é probabilidade)' })).toBeTruthy();
    expect(table.getByRole('columnheader', { name: 'Probabilidade exata do prêmio principal' })).toBeTruthy();
    const rows = table.getAllByRole('row').slice(1);
    expect(rows).toHaveLength(5);
    rows.forEach((row, i) => {
      const cells = within(row).getAllByRole('cell');
      expect(cells[0].textContent).toBe(String(i + 1));
      expect(within(row).getByLabelText('Dezenas: ' + d.tickets[i].numbers.map((n) => String(n).padStart(2, '0')).join(', '))).toBeTruthy();
      expect(cells[2].textContent).toContain('0,125');
      expect(cells[2].textContent).toContain('Peso médio das dezenas');
      expect(cells[3].textContent).toContain(`1 / ${m.fraction}`);
      expect(cells[4].textContent).toMatch(new RegExp(`R\\$\\s*${m.costLabel}`));
    });
  });

  it('mostra a nota do worker quando não há backtest associado', async () => {
    const d = detail();
    const note = 'Sem experimento de backtest concluído para este método.';
    serve({ ...d, set: { ...d.set, evidence: null, explanation: { ...d.set.explanation, evidence_note: note } } });
    render(<GeneratorPage suggestionId="3" />);
    expect(await screen.findByText(note)).toBeTruthy();
  });

  it.each([
    ['conjunto ausente', { set: null, tickets: [] }],
    ['lista de bilhetes ausente', { set: detail().set, tickets: null }],
    ['quantidade de bilhetes divergente', { ...detail(), tickets: detail().tickets.slice(0, 1) }],
    ['bilhete sem dezenas', { ...detail(), tickets: detail().tickets.map((t) => ({ ...t, numbers: null })) }],
    ['bilhete sem probabilidade exata', { ...detail(), tickets: detail().tickets.map((t) => ({ ...t, exact_jackpot_probability: null })) }],
  ])('avisa que a resposta está incompleta: %s', async (_label, body) => {
    serve(body);
    render(<GeneratorPage suggestionId="3" />);
    expect(await screen.findByText('Resposta incompleta para o conjunto de sugestões.')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Gerador experimental' })).toBeTruthy();
    expect(screen.queryByRole('table', { name: 'Bilhetes sugeridos' })).toBeNull();
  });

  it('mostra carregamento e mantém o formulário disponível enquanto a geração está na fila', async () => {
    const d = detail();
    serve({ ...d, set: { ...d.set, status: 'pending', explanation: null, evidence: null, jackpot_probability: null }, tickets: [] });
    render(<GeneratorPage suggestionId="3" />);
    expect(screen.getAllByRole('status', { name: 'Carregando' }).length).toBeGreaterThan(0);
    expect(await screen.findByText('Na fila')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Gerar' })).toBeTruthy();
  });

  it('informa a falha do processamento sem apresentar bilhetes', async () => {
    const d = detail();
    serve({ ...d, set: { ...d.set, status: 'failed', explanation: null, evidence: null, jackpot_probability: null }, tickets: [] });
    render(<GeneratorPage suggestionId="3" />);
    expect(await screen.findByText('A geração falhou.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Gerar' })).toBeTruthy();
    expect(screen.queryByRole('table', { name: 'Bilhetes sugeridos' })).toBeNull();
  });

  it('informa a falha HTTP e oferece nova tentativa', async () => {
    serve({ error: 'Falha no servidor' }, 500);
    render(<GeneratorPage suggestionId="3" />);
    expect(await screen.findByText('Falha no servidor')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Tentar novamente' })).toBeTruthy();
  });

  it('distingue um conjunto inexistente de uma geração em andamento', async () => {
    serve({ error: 'Conjunto não encontrado' }, 404);
    render(<GeneratorPage suggestionId="3" />);
    expect(await screen.findByText('Conjunto #3 não encontrado.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Gerar' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Gerando…' })).toBeNull();
  });
});
