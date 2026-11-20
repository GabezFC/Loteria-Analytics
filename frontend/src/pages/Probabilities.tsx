import { useEffect, useState, type FormEvent } from 'react';
import { api } from '../api/client';
import type { Lottery, LotteryInfo, Probabilities } from '../api/types';
import { LOTTERIES } from '../api/types';
import { useApi } from '../lib/useApi';
import { AsyncView, Card, ErrorBox, Field, Notice, PageHeader, Skeleton, Stat, Table, Tag } from '../components/ui';
import { fmtBRL, fmtFraction, fmtInt, fmtOneIn, fmtProb } from '../lib/format';
import { LOTTERY_NAMES } from '../lib/names';

type Mode = 'none' | 'tickets' | 'budget';
interface Applied {
  lottery: Lottery;
  bet_size?: number;
  hits?: number;
  tickets?: number;
  budget?: number;
  contests: number;
}

export function ProbabilitiesPage({ initialLottery = 'megasena' as Lottery }: { initialLottery?: Lottery }) {
  const lots = useApi((s) => api.lotteries(s), [], { key: 'lotteries' });
  const [lottery, setLottery] = useState<Lottery>(initialLottery);
  const [betSize, setBetSize] = useState('');
  const [mode, setMode] = useState<Mode>('tickets');
  const [amount, setAmount] = useState('1');
  const [contests, setContests] = useState('1');
  const [hits, setHits] = useState('');
  const [applied, setApplied] = useState<Applied>({ lottery: initialLottery, tickets: 1, contests: 1 });
  const [formError, setFormError] = useState<string | null>(null);

  const info: LotteryInfo | undefined = lots.state.status === 'ok' ? lots.state.data.items.find((l) => l.slug === lottery) : undefined;
  const bet = betSize === '' ? (info?.min_bet_size ?? 0) : Number(betSize);
  const simple = info ? bet === info.min_bet_size : true;

  useEffect(() => setBetSize(''), [lottery]);

  const prob = useApi((s) => api.probabilities(applied, s), [JSON.stringify(applied)], { key: 'prob:' + JSON.stringify(applied) });

  function submit(e: FormEvent) {
    e.preventDefault();
    const c = Number(contests);
    if (!Number.isInteger(c) || c < 1 || c > 10000) return setFormError('Nº de concursos deve ser um inteiro entre 1 e 10.000.');
    const next: Applied = { lottery, contests: c };
    if (betSize !== '') {
      if (!info || !Number.isInteger(bet) || bet < info.min_bet_size || bet > info.max_bet_size) return setFormError('Tamanho da aposta fora do permitido para a modalidade.');
      next.bet_size = bet;
    }
    if (hits !== '') {
      const h = Number(hits);
      if (!Number.isInteger(h) || h < 0 || (info && h > info.draw_size)) return setFormError('Faixa de acerto inválida.');
      next.hits = h;
    }
    if (simple && mode !== 'none') {
      const a = Number(amount.replace(',', '.'));
      if (!Number.isFinite(a) || a <= 0) return setFormError('Informe um valor positivo para bilhetes/orçamento.');
      if (mode === 'tickets') {
        if (!Number.isInteger(a)) return setFormError('Nº de bilhetes deve ser inteiro.');
        next.tickets = a;
      } else next.budget = a;
    }
    setFormError(null);
    setApplied(next);
  }

  return (
    <>
      <PageHeader title="Probabilidades" subtitle="Chances matemáticas exatas (distribuição hipergeométrica). Não dependem do histórico." />
      <Card title="Calculadora">
        <form className="form" onSubmit={submit} aria-label="Calculadora de probabilidades">
          <Field label="Modalidade">
            <select value={lottery} onChange={(e) => setLottery(e.target.value as Lottery)}>
              {LOTTERIES.map((l) => (
                <option key={l} value={l}>
                  {LOTTERY_NAMES[l]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Tamanho da aposta (dezenas)" hint={info ? 'De ' + info.min_bet_size + ' a ' + info.max_bet_size + ' (padrão: ' + info.min_bet_size + ')' : undefined}>
            <input type="number" inputMode="numeric" min={info?.min_bet_size} max={info?.max_bet_size} value={betSize} placeholder={info ? String(info.min_bet_size) : ''} onChange={(e) => setBetSize(e.target.value)} />
          </Field>
          <Field label="Quantidade de bilhetes distintos ou orçamento" hint={simple ? undefined : 'Disponível só para aposta simples (tamanho mínimo).'}>
            <div className="inline">
              <select value={mode} onChange={(e) => setMode(e.target.value as Mode)} disabled={!simple} aria-label="Tipo de quantidade">
                <option value="tickets">Bilhetes</option>
                <option value="budget">Orçamento (R$)</option>
                <option value="none">Nenhum</option>
              </select>
              <input type="text" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} disabled={!simple || mode === 'none'} aria-label="Valor" />
            </div>
          </Field>
          <Field label="Nº de concursos independentes" hint="1 a 10.000">
            <input type="number" inputMode="numeric" min={1} max={10000} value={contests} onChange={(e) => setContests(e.target.value)} />
          </Field>
          <Field label="Faixa de acerto (opcional)" hint="Filtra uma linha da tabela">
            <input type="number" inputMode="numeric" min={0} max={info?.draw_size} value={hits} onChange={(e) => setHits(e.target.value)} />
          </Field>
          <div className="form-actions">
            <button className="btn btn-primary" type="submit">
              Calcular
            </button>
          </div>
        </form>
        {formError && (
          <p className="form-error" role="alert">
            {formError}
          </p>
        )}
      </Card>
      <Notice tone="warn" title="Chance de algum prêmio ≠ retorno positivo.">
        Acertar uma faixa premiada pode render menos do que o custo da aposta. O custo é certo; o prêmio, não. Esta calculadora não recomenda apostar.
      </Notice>
      <AsyncView state={prob.state} onRetry={prob.reload} what="O cálculo" skeleton={<Card><Skeleton lines={6} height={20} /></Card>}>
        {(p) => <ProbResult p={p} contests={applied.contests} />}
      </AsyncView>
      <Formulas />
      {lots.state.status === 'error' && <ErrorBox error={lots.state.error} what="A lista de modalidades" />}
    </>
  );
}

export function ProbResult({ p, contests }: { p: Probabilities; contests: number }) {
  const tj = p.tickets_jackpot;
  return (
    <>
      <Card title={'Resultado — ' + (LOTTERY_NAMES[p.lottery] ?? p.lottery)}>
        <div className="stats">
          <Stat label="Combinações possíveis" value={'C(' + p.pool_size + ', ' + p.draw_size + ') = ' + fmtInt(p.total_combinations)} />
          <Stat label="Aposta" value={p.bet_size + ' dezenas'} hint={fmtInt(p.simple_games) + ' jogo(s) simples'} />
          <Stat label="Custo da aposta" value={fmtBRL(p.bet_cost)} hint={'preço simples ' + fmtBRL(p.simple_price)} />
          <Stat label="Concursos" value={fmtInt(contests)} hint="independentes" />
        </div>
        <p className="small muted">Preço: {p.price_source} · fórmula {p.formula_version}</p>
      </Card>
      <Card title="Faixas de acerto">
        <Table caption="Probabilidade por faixa de acerto">
          <thead>
            <tr>
              <th>Acertos</th>
              <th>Premiada?</th>
              <th className="r">Fração exata</th>
              <th className="r">1 em X</th>
              <th className="r">Probabilidade</th>
              <th className="r">Pelo menos</th>
            </tr>
          </thead>
          <tbody>
            {p.tiers.map((t) => (
              <tr key={t.hits}>
                <td className="num">{t.hits}</td>
                <td>{t.is_prize_tier ? <Tag tone="info">Faixa premiada</Tag> : <span className="muted">—</span>}</td>
                <td className="r num">{fmtFraction(t.exact)}</td>
                <td className="r num">{fmtOneIn(t.one_in, t.exact)}</td>
                <td className="r num">{fmtProb(t.probability)}</td>
                <td className="r num" title={fmtFraction(t.at_least)}>
                  {fmtProb(t.at_least_probability)}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      {tj && (
        <Card title="Prêmio principal com vários bilhetes e concursos">
          <div className="stats">
            <Stat label="Bilhetes distintos" value={fmtInt(tj.count)} hint={tj.budget !== undefined ? 'orçamento ' + fmtBRL(tj.budget) + (tj.spent !== undefined ? ' · gasto ' + fmtBRL(tj.spent) : '') : undefined} />
            <Stat label="Concursos" value={fmtInt(tj.contests)} />
            <Stat label="Probabilidade de ganhar o prêmio principal" value={fmtProb(tj.probability)} hint={fmtOneIn(tj.one_in, tj.fraction)} />
          </div>
          {tj.fraction && <p className="small muted">Fração exata: {fmtFraction(tj.fraction)}.</p>}
        </Card>
      )}
      <Card title="Premissas da resposta">
        <ul className="bullets">
          {p.assumptions.map((a, i) => (
            <li key={i}>{a}</li>
          ))}
        </ul>
      </Card>
    </>
  );
}

function Formulas() {
  return (
    <Card title="Como o cálculo funciona">
      <ul className="bullets">
        <li>
          <strong>Combinações:</strong> C(N, k) = N! / (k! · (N − k)!) é o número de conjuntos distintos de k dezenas num universo de N. Cada combinação sorteada é igualmente provável.
        </li>
        <li>
          <strong>Hipergeométrica:</strong> com uma aposta de b dezenas, sorteio de k dezenas em N, a probabilidade de exatamente h acertos é C(b, h) · C(N − b, k − h) / C(N, k).
        </li>
        <li>
          <strong>“Pelo menos h”:</strong> soma das probabilidades de h, h+1, …, k acertos.
        </li>
        <li>
          <strong>Vários concursos:</strong> sorteios independentes; P(ao menos um) = 1 − (1 − p)^n. O histórico não muda p.
        </li>
        <li>
          <strong>Mais bilhetes:</strong> m bilhetes distintos multiplicam a chance por m (aproximadamente), e o custo também. Não existe combinação “melhor”.
        </li>
      </ul>
    </Card>
  );
}
