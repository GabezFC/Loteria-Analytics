"""Validated Caixa XLSX collector (draws + prize tiers).

Run: python ingest.py [slug ...]            incremental/idempotent import
     python ingest.py --resolve ID accept|reject [--note TEXT]   resolve a source divergence

Guarantees:
- The whole workbook is parsed before any write; structural errors abort without touching the DB.
- Invalid rows go to ingest_quarantine and never reach lottery_draw.
- A contest already validated is never overwritten silently: different numbers/date create an
  open row in ingest_divergence and the validated value is kept until an explicit decision.
- Prize tiers are reconciled with an audit trail (ingest_draw_change).
- New/changed data enqueues an `analyze` job and emits NOTIFY cassino_analysis_ready in the same
  transaction as the run completion.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable

import psycopg
from openpyxl import load_workbook

BASE_URL = "https://servicebus3.caixa.gov.br/portaldeloterias/api/resultados/download"
ADAPTER_VERSION = "caixa-xlsx-v2"
BATCH_SIZE = 250
MAX_BYTES = 25 * 1024 * 1024
RETRIES = 3
MAX_REJECT_RATIO = 0.01  # acima disso o arquivo é considerado estruturalmente suspeito
MIN_REJECT_ALLOWANCE = 5


@dataclass(frozen=True)
class Lottery:
    slug: str
    official_name: str
    draw_size: int
    pool_size: int
    prize_hits: tuple[int, ...]


LOTTERIES = {
    "megasena": Lottery("megasena", "Mega-Sena", 6, 60, (6, 5, 4)),
    "lotofacil": Lottery("lotofacil", "Lotofácil", 15, 25, (15, 14, 13, 12, 11)),
    "quina": Lottery("quina", "Quina", 5, 80, (5, 4, 3, 2)),
}

Tier = tuple[int, int, Decimal]  # hits, winners, payout per winner


@dataclass(frozen=True)
class Draw:
    contest: int
    draw_date: date
    numbers: tuple[int, ...]
    tiers: tuple[Tier, ...] | None = None  # None = prêmios ausentes/inválidos: não tocar
    extra: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class Reject:
    line: int
    contest: int | None
    kind: str  # 'draw' | 'prize'
    reason: str
    raw: tuple


@dataclass(frozen=True)
class Parsed:
    draws: list[Draw]
    rejects: list[Reject]


def _key(value: object) -> str:
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]", "", s)


def _column_indexes(headers: Iterable[object], lottery: Lottery) -> tuple[int, int, list[int]]:
    values = [_key(v) for v in headers]
    contest = next((i for i, v in enumerate(values) if v in {"concurso", "numero do concurso", "numerodoconcurso"}), None)
    draw_date = next((i for i, v in enumerate(values) if v in {"datadosorteio", "datasorteio", "data"}), None)
    if contest is None or draw_date is None:
        raise ValueError(f"Cabeçalho não reconhecido: requer Concurso e Data do Sorteio; recebido={list(headers)!r}")
    balls: dict[int, int] = {}
    for i, v in enumerate(values):
        m = re.search(r"(?:dezena|bola|numero)(\d+)$", v)
        if m:
            balls[int(m.group(1))] = i
    indexes = [balls[i] for i in range(1, lottery.draw_size + 1) if i in balls]
    if len(indexes) != lottery.draw_size:
        raise ValueError(f"Cabeçalho requer {lottery.draw_size} colunas de dezenas numeradas sequencialmente; recebido={list(headers)!r}")
    return contest, draw_date, indexes


def _prize_columns(headers: Iterable[object], lottery: Lottery, require: bool) -> dict[int, tuple[int, int]]:
    """hits -> (índice ganhadores, índice rateio)."""
    winners: dict[int, int] = {}
    payouts: dict[int, int] = {}
    for i, v in enumerate(_key(h) for h in headers):
        m = re.fullmatch(r"ganhadores(\d+)acertos", v)
        if m:
            winners[int(m.group(1))] = i
        m = re.fullmatch(r"rateio(\d+)acertos", v)
        if m:
            payouts[int(m.group(1))] = i
    cols = {h: (winners[h], payouts[h]) for h in lottery.prize_hits if h in winners and h in payouts}
    if require and len(cols) != len(lottery.prize_hits):
        raise ValueError(f"Cabeçalho sem colunas de premiação completas para {lottery.slug}: esperado faixas {lottery.prize_hits}, encontrado {sorted(cols)}")
    return cols


_MONEY = re.compile(r"^(?:R\$)?\s*(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?$")


def parse_money(value: object) -> Decimal | None:
    """'R$1.234,56' -> Decimal('1234.56'); vazio -> None; inválido -> ValueError."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError("valor monetário inválido")
    if isinstance(value, (int, float, Decimal)):
        d = Decimal(str(value))
    else:
        m = _MONEY.match(str(value).strip())
        if not m:
            raise ValueError(f"valor monetário inválido: {value!r}")
        d = Decimal(m.group(1).replace(".", "") + "." + (m.group(2) or "0"))
    if d < 0:
        raise ValueError("valor monetário negativo")
    try:
        return d.quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ValueError("valor monetário fora de faixa") from None


def _parse_int(value: object) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError()
    n = int(value)
    if float(value) != n:
        raise ValueError()
    return n


def _extra_indexes(headers: Iterable[object], lottery: Lottery) -> dict[str, int]:
    out: dict[str, int] = {}
    for i, v in enumerate(_key(h) for h in headers):
        if v == "cidadeuf":
            out["winner_locations"] = i
        elif v == f"acumulado{lottery.prize_hits[0]}acertos":
            out["accumulated_main"] = i
        elif v == "arrecadacaototal":
            out["total_collected"] = i
        elif v == "estimativapremio":
            out["next_estimate"] = i
        elif v.startswith("acumuladosorteioespecial"):
            out["special_accumulated"] = i
        elif v == "observacao":
            out["observation"] = i
    return out


def parse_workbook(data: bytes, lottery: Lottery, require_prizes: bool = False) -> Parsed:
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValueError("Resposta não é um XLSX/ZIP válido")
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        ws = wb.active
        if ws is None or not hasattr(ws, "reset_dimensions"):
            raise ValueError("Workbook sem planilha ativa de resultados")
        # Official XLSX files declare a header-only dimension despite containing the history.
        ws.reset_dimensions()
        it = ws.iter_rows(values_only=True)
        try:
            headers = next(it)
        except StopIteration:
            raise ValueError("Workbook sem linhas")
        ci, di, ni = _column_indexes(headers, lottery)
        prize_cols = _prize_columns(headers, lottery, require_prizes)
        extra_cols = _extra_indexes(headers, lottery)
        draws: list[Draw] = []
        rejects: list[Reject] = []
        seen: set[int] = set()
        total_rows = 0
        for line, row in enumerate(it, start=2):
            if not row or all(v is None or str(v).strip() == "" for v in row):
                continue
            total_rows += 1
            contest: int | None = None
            try:
                contest = _parse_int(row[ci])
                if contest < 1:
                    raise ValueError()
                date_raw = row[di]
                if isinstance(date_raw, datetime):
                    draw_date = date_raw.date()
                elif isinstance(date_raw, date):
                    draw_date = date_raw
                elif isinstance(date_raw, str):
                    text = date_raw.strip()
                    draw_date = datetime.strptime(text, "%d/%m/%Y").date() if "/" in text else date.fromisoformat(text)
                else:
                    raise ValueError()
                raw_numbers = [row[i] for i in ni]
                numbers = tuple(_parse_int(n) for n in raw_numbers)
                if len(set(numbers)) != lottery.draw_size or any(n < 1 or n > lottery.pool_size for n in numbers):
                    raise ValueError()
            except (ValueError, TypeError, IndexError, OverflowError):
                rejects.append(Reject(line, contest, "draw", "concurso, data ou dezenas fora do contrato", tuple(_jsonable(v) for v in row)))
                continue
            if contest in seen:
                raise ValueError(f"Workbook contém concurso duplicado ({contest})")
            seen.add(contest)
            tiers: tuple[Tier, ...] | None = None
            if prize_cols:
                try:
                    built = []
                    for hits, (wi, pi) in sorted(prize_cols.items(), reverse=True):
                        w = _parse_int(row[wi])
                        p = parse_money(row[pi])
                        if w < 0 or p is None:
                            raise ValueError("faixa sem ganhadores/rateio")
                        built.append((hits, w, p))
                    tiers = tuple(built)
                except (ValueError, TypeError, IndexError, OverflowError) as exc:
                    rejects.append(Reject(line, contest, "prize", f"premiação inválida: {exc}", tuple(_jsonable(v) for v in row)))
            extra: dict = {}
            for name, idx in extra_cols.items():
                value = row[idx] if idx < len(row) else None
                if name in ("winner_locations", "observation"):
                    text = str(value).strip() if value is not None else ""
                    extra[name] = text[:2000] or None
                else:
                    try:
                        extra[name] = parse_money(value)
                    except ValueError:
                        extra[name] = None
            draws.append(Draw(contest, draw_date, tuple(sorted(numbers)), tiers, extra))
        if not draws:
            raise ValueError("Workbook não contém concursos válidos")
        limit = max(MIN_REJECT_ALLOWANCE, int(total_rows * MAX_REJECT_RATIO))
        if len(rejects) > limit:
            raise ValueError(f"{len(rejects)} linhas rejeitadas de {total_rows}: formato da fonte suspeito, nada foi gravado")
        draws.sort(key=lambda d: d.contest)
        return Parsed(draws, rejects)
    finally:
        wb.close()


def _jsonable(v: object) -> object:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def download(lottery: Lottery) -> tuple[bytes, str]:
    url = BASE_URL + "?" + urllib.parse.urlencode({"modalidade": lottery.official_name})
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Cassino-LoteriaAnalytics/1.0", "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, application/xlsx"})
            with urllib.request.urlopen(req, timeout=25) as response:
                if response.status != 200:
                    raise RuntimeError(f"CAIXA retornou HTTP {response.status}")
                content_type = response.headers.get_content_type().lower()
                if content_type not in {"application/xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/octet-stream"}:
                    raise ValueError(f"Content-Type inesperado: {content_type}")
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError("XLSX excede o limite de 25 MiB")
            if not zipfile.is_zipfile(io.BytesIO(data)):
                raise ValueError("Resposta HTTP 200 não contém XLSX válido")
            return data, url
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
            last = exc
            if attempt + 1 < RETRIES:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Falha no download oficial após {RETRIES} tentativas: {last}")


def _connect():
    return psycopg.connect(connect_timeout=5, application_name="cassino-ingest")


_PREFETCH = """
SELECT d.draw_id, d.contest, d.draw_date,
       COALESCE((SELECT array_agg(n.number ORDER BY n.number) FROM draw_number n WHERE n.draw_id = d.draw_id), '{}'::smallint[]),
       COALESCE((SELECT jsonb_agg(jsonb_build_array(t.hits, t.winners, t.payout_amount::text) ORDER BY t.hits DESC)
                   FROM draw_prize_tier t WHERE t.draw_id = d.draw_id), '[]'::jsonb)
  FROM lottery_draw d
 WHERE d.lottery_slug = %s AND d.contest = ANY(%s)
   FOR UPDATE OF d"""

_EXTRA_COLS = ("winner_locations", "accumulated_main", "total_collected", "next_estimate", "special_accumulated", "observation")


def _tiers_key(tiers: Iterable[Tier]) -> list[list]:
    return [[h, w, str(p)] for h, w, p in tiers]


def _write_extra(cur, draw_id: int, extra: dict) -> None:
    values = [extra.get(c) for c in _EXTRA_COLS]
    if all(v is None for v in values):
        return
    cur.execute(
        "INSERT INTO draw_extra(draw_id," + ",".join(_EXTRA_COLS) + ") VALUES (%s," + ",".join(["%s"] * len(_EXTRA_COLS)) + ") "
        "ON CONFLICT (draw_id) DO UPDATE SET " + ",".join(f"{c}=EXCLUDED.{c}" for c in _EXTRA_COLS),
        [draw_id, *values],
    )


def _apply_batch(cur, lottery: Lottery, batch: list[Draw], digest: str, run_id: int) -> dict[str, int]:
    counts = {"inserted": 0, "unchanged": 0, "divergent": 0, "prize_changed": 0}
    cur.execute(_PREFETCH, (lottery.slug, [d.contest for d in batch]))
    existing = {r[1]: r for r in cur.fetchall()}
    for draw in batch:
        row = existing.get(draw.contest)
        if row is None:
            cur.execute("INSERT INTO lottery_draw(lottery_slug,contest,draw_date,source_sha256,ingest_run_id) VALUES (%s,%s,%s,%s,%s) RETURNING draw_id", (lottery.slug, draw.contest, draw.draw_date, digest, run_id))
            draw_id = cur.fetchone()[0]
            cur.executemany("INSERT INTO draw_number(draw_id,number) VALUES (%s,%s)", [(draw_id, n) for n in draw.numbers])
            if draw.tiers:
                cur.executemany("INSERT INTO draw_prize_tier(draw_id,hits,winners,payout_amount) VALUES (%s,%s,%s,%s)", [(draw_id, *t) for t in draw.tiers])
            _write_extra(cur, draw_id, draw.extra)
            counts["inserted"] += 1
            continue
        draw_id, _, old_date, old_numbers, old_tiers = row
        if old_date != draw.draw_date or tuple(old_numbers) != draw.numbers:
            # Divergência: preserva o valor validado e registra para decisão explícita.
            cur.execute(
                "INSERT INTO ingest_divergence(ingest_run_id,draw_id,previous_value,current_value) "
                "VALUES (%s,%s,jsonb_build_object('draw_date',%s::text,'numbers',%s::smallint[]),jsonb_build_object('draw_date',%s::text,'numbers',%s::smallint[])) "
                "ON CONFLICT (draw_id, md5(current_value::text)) WHERE status = 'open' DO NOTHING",
                (run_id, draw_id, old_date, list(old_numbers), draw.draw_date, list(draw.numbers)),
            )
            counts["divergent"] += cur.rowcount
            continue
        changed = False
        if draw.tiers is not None and _tiers_key(draw.tiers) != old_tiers:
            if old_tiers:
                cur.execute(
                    "INSERT INTO ingest_draw_change(ingest_run_id,draw_id,action,previous_value,current_value) VALUES (%s,%s,'prize_reconciled',%s::jsonb,%s::jsonb)",
                    (run_id, draw_id, json.dumps({"tiers": old_tiers}), json.dumps({"tiers": _tiers_key(draw.tiers)})),
                )
            cur.execute("DELETE FROM draw_prize_tier WHERE draw_id=%s", (draw_id,))
            cur.executemany("INSERT INTO draw_prize_tier(draw_id,hits,winners,payout_amount) VALUES (%s,%s,%s,%s)", [(draw_id, *t) for t in draw.tiers])
            counts["prize_changed"] += 1
            changed = True
        _write_extra(cur, draw_id, draw.extra)
        if not changed:
            counts["unchanged"] += 1
    return counts


def ingest_one(lottery: Lottery, data: bytes, source_url: str, batch_size: int = BATCH_SIZE) -> dict:
    digest = hashlib.sha256(data).hexdigest()
    parsed = parse_workbook(data, lottery, require_prizes=True)  # valida tudo antes de qualquer gravação
    draws = parsed.draws
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT slug FROM lottery_type WHERE slug=%s AND name=%s AND draw_size=%s AND pool_size=%s", (lottery.slug, lottery.official_name, lottery.draw_size, lottery.pool_size))
            if cur.fetchone() is None:
                raise RuntimeError(f"lottery_type não corresponde ao contrato para {lottery.slug}")
            cur.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", ("cassino-ingest:" + lottery.slug,))
            if not cur.fetchone()[0]:
                raise RuntimeError(f"Ingestão concorrente já em execução para {lottery.slug}")
            cur.execute("INSERT INTO ingest_run(lottery_slug, source_url, source_sha256, source_bytes, adapter_version, status, started_at, row_count, inserted_count, updated_count, unchanged_count) VALUES (%s,%s,%s,%s,%s,'running',now(),%s,0,0,0) RETURNING ingest_run_id", (lottery.slug, source_url, digest, len(data), ADAPTER_VERSION, len(draws)))
            run_id = cur.fetchone()[0]
        conn.commit()  # Libera o registro running; mantém o advisory lock por sessão.
        totals = {"inserted": 0, "unchanged": 0, "divergent": 0, "prize_changed": 0}
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    for rj in parsed.rejects:
                        cur.execute(
                            "INSERT INTO ingest_quarantine(ingest_run_id,lottery_slug,contest,source_line,kind,reason,raw_row) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)",
                            (run_id, lottery.slug, rj.contest, rj.line, rj.kind, rj.reason, json.dumps(rj.raw, default=str)),
                        )
            for start in range(0, len(draws), batch_size):
                batch = draws[start:start + batch_size]
                with conn.transaction():
                    with conn.cursor() as cur:
                        counts = _apply_batch(cur, lottery, batch, digest, run_id)
                        cur.execute("UPDATE ingest_run SET checkpoint_contest=%s WHERE ingest_run_id=%s", (batch[-1].contest, run_id))
                for k, v in counts.items():
                    totals[k] += v
            changed = totals["inserted"] + totals["prize_changed"] > 0
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE ingest_run SET status='succeeded', completed_at=now(), inserted_count=%s, updated_count=%s, unchanged_count=%s, "
                        "quarantined_count=%s, divergent_count=%s, prize_changed_count=%s, checkpoint_contest=%s WHERE ingest_run_id=%s",
                        (totals["inserted"], 0, totals["unchanged"], len(parsed.rejects), totals["divergent"], totals["prize_changed"], draws[-1].contest, run_id),
                    )
                    if changed:
                        cur.execute(
                            "INSERT INTO job(kind, lottery_slug, ingest_run_id) VALUES ('analyze', %s, %s) ON CONFLICT (kind, COALESCE(lottery_slug, ''), md5(params::text)) WHERE status = 'pending' DO NOTHING",
                            (lottery.slug, run_id),
                        )
                        cur.execute("SELECT pg_notify('cassino_analysis_ready', %s)", (f"{run_id}:{lottery.slug}:{digest}",))
            return {"run_id": run_id, "slug": lottery.slug, "hash": digest, "rows": len(draws), "quarantined": len(parsed.rejects), "analysis_enqueued": changed, **totals}
        except Exception as exc:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("UPDATE ingest_run SET status='failed', completed_at=now(), error_message=%s WHERE ingest_run_id=%s", (str(exc)[:1000], run_id))
            raise
        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", ("cassino-ingest:" + lottery.slug,))


def run(slugs: list[str]) -> int:
    failed = False
    for slug in slugs:
        if not collect(slug):
            failed = True
    return int(failed)


def collect(slug: str) -> bool:
    """Download + ingest de uma modalidade. Nunca propaga exceção (falha externa não derruba o chamador)."""
    lottery = LOTTERIES[slug]
    try:
        data, url = download(lottery)
        r = ingest_one(lottery, data, url)
        print(
            f"ingestão {slug} concluída: run={r['run_id']} linhas={r['rows']} inseridos={r['inserted']} inalterados={r['unchanged']} "
            f"premios_alterados={r['prize_changed']} divergencias={r['divergent']} quarentena={r['quarantined']} sha256={r['hash']}",
            flush=True,
        )
        return True
    except Exception as exc:
        print(f"ingestão {slug} falhou: {exc}", file=sys.stderr, flush=True)
        return False


def resolve_divergence(divergence_id: int, decision: str, note: str | None = None) -> None:
    """accept: aplica dezenas/data da fonte (com trilha); reject: mantém o valor validado."""
    if decision not in {"accept", "reject"}:
        raise ValueError("decisão deve ser accept ou reject")
    with _connect() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT draw_id, previous_value, current_value, ingest_run_id FROM ingest_divergence WHERE divergence_id=%s AND status='open' FOR UPDATE", (divergence_id,))
                row = cur.fetchone()
                if row is None:
                    raise ValueError(f"divergência {divergence_id} inexistente ou já resolvida")
                draw_id, prev, cur_val, run_id = row
                if decision == "accept":
                    numbers = [int(n) for n in cur_val["numbers"]]
                    cur.execute("INSERT INTO ingest_draw_change(ingest_run_id,draw_id,action,previous_value,current_value) VALUES (%s,%s,'reconciled',%s::jsonb,%s::jsonb)", (run_id, draw_id, json.dumps(prev), json.dumps(cur_val)))
                    cur.execute("UPDATE lottery_draw SET draw_date=%s::date, updated_at=now() WHERE draw_id=%s", (cur_val["draw_date"], draw_id))
                    cur.execute("DELETE FROM draw_number WHERE draw_id=%s", (draw_id,))
                    cur.executemany("INSERT INTO draw_number(draw_id,number) VALUES (%s,%s)", [(draw_id, n) for n in numbers])
                    cur.execute("SELECT lottery_slug FROM lottery_draw WHERE draw_id=%s", (draw_id,))
                    slug = cur.fetchone()[0]
                    cur.execute("INSERT INTO job(kind, lottery_slug) VALUES ('analyze', %s) ON CONFLICT (kind, COALESCE(lottery_slug, ''), md5(params::text)) WHERE status = 'pending' DO NOTHING", (slug,))
                    cur.execute("SELECT pg_notify('cassino_analysis_ready', %s)", (f"divergence:{divergence_id}:{slug}",))
                cur.execute("UPDATE ingest_divergence SET status=%s, resolved_at=now(), resolution_note=%s WHERE divergence_id=%s", ("accepted" if decision == "accept" else "rejected", note, divergence_id))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("slugs", nargs="*", choices=sorted(LOTTERIES), default=list(LOTTERIES))
    parser.add_argument("--resolve", nargs=2, metavar=("ID", "accept|reject"))
    parser.add_argument("--note")
    args = parser.parse_args()
    if args.resolve:
        resolve_divergence(int(args.resolve[0]), args.resolve[1], args.note)
        print(f"divergência {args.resolve[0]} resolvida: {args.resolve[1]}")
        return 0
    return run(args.slugs)


if __name__ == "__main__":
    raise SystemExit(main())
