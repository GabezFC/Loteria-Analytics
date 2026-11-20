"""Probabilidades combinatórias exatas (apenas biblioteca padrão; frações exatas).

Modelo: sorteio uniforme de k dezenas distintas entre N, concursos independentes.
Aposta de `b` dezenas (b >= k). X = número de dezenas sorteadas contidas na aposta.

    P(X = r)  = C(b, r) * C(N-b, k-r) / C(N, k)          (hipergeométrica)
    jogos simples contidos na aposta = C(b, k)             (custo = C(b,k) * preço simples)
    jogos simples da aposta com exatamente h acertos, dado X = r: C(r, h) * C(b-r, k-h)

Chance de prêmio máximo com m bilhetes simples DISTINTOS num mesmo concurso: m / C(N, k)
(m <= C(N, k)). Para c concursos independentes com os mesmos m bilhetes: 1 - (1 - m/C(N,k))^c.
Nada aqui usa histórico: o histórico não altera a probabilidade do próximo sorteio.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import comb

FORMULA_VERSION = "hypergeom-exact-v1"


def combinations_total(pool: int, draw: int) -> int:
    _check(pool, draw)
    return comb(pool, draw)


def _check(pool: int, draw: int, bet: int | None = None) -> None:
    if not (0 < draw <= pool):
        raise ValueError("requer 0 < k <= N")
    if bet is not None and not (draw <= bet <= pool):
        raise ValueError("tamanho da aposta deve estar entre k e N")


def hits_probability(pool: int, draw: int, bet: int, hits: int) -> Fraction:
    """P(exatamente `hits` dezenas sorteadas dentro da aposta de `bet` dezenas)."""
    _check(pool, draw, bet)
    if not (0 <= hits <= draw):
        return Fraction(0)
    return Fraction(comb(bet, hits) * comb(pool - bet, draw - hits), comb(pool, draw))


def at_least_probability(pool: int, draw: int, bet: int, hits: int) -> Fraction:
    return sum((hits_probability(pool, draw, bet, r) for r in range(max(hits, 0), draw + 1)), Fraction(0))


def simple_games(draw: int, bet: int) -> int:
    return comb(bet, draw)


def games_with_hits(draw: int, bet: int, drawn_inside: int, hits: int) -> int:
    """Quantos jogos simples da aposta fazem exatamente `hits`, quando `drawn_inside` dezenas sorteadas estão na aposta."""
    return comb(drawn_inside, hits) * comb(bet - drawn_inside, draw - hits)


def jackpot_with_tickets(pool: int, draw: int, tickets: int, contests: int = 1) -> Fraction:
    """Probabilidade de ao menos um prêmio máximo com `tickets` bilhetes simples distintos por concurso."""
    total = comb(pool, draw)
    if not (0 <= tickets <= total):
        raise ValueError("bilhetes distintos devem estar entre 0 e C(N,k)")
    if contests < 1:
        raise ValueError("contests >= 1")
    per = Fraction(tickets, total)
    return Fraction(1) - (1 - per) ** contests


@dataclass(frozen=True)
class TierRow:
    bet_size: int
    hits: int
    is_prize_tier: bool
    exact: Fraction
    at_least: Fraction
    simple_games: int


def tier_table(pool: int, draw: int, prize_hits: tuple[int, ...], min_bet: int, max_bet: int) -> list[TierRow]:
    rows: list[TierRow] = []
    for b in range(min_bet, max_bet + 1):
        games = simple_games(draw, b)
        for r in range(draw + 1):
            rows.append(TierRow(b, r, r in prize_hits, hits_probability(pool, draw, b, r), at_least_probability(pool, draw, b, r), games))
    return rows
