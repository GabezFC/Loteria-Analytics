# Cassino — Loteria Analytics

Aplicação **local** de análise estatística dos resultados oficiais da Mega-Sena, Lotofácil e Quina: probabilidades exatas,
estatística descritiva e inferencial, simulações Monte Carlo e backtests cronológicos. **Não realiza apostas, não acessa contas
de loteria e não prevê resultados.** Sorteios justos são independentes e uniformes; nenhum método aqui aumenta a chance de ganhar.

Separação obrigatória (também na interface): **probabilidade exata ≠ frequência histórica ≠ score heurístico ≠ resultado de modelo**.

## Arquitetura (V1)

```
Navegador ─ http://127.0.0.1:3000 ─► frontend (React + Nginx) ─ /api/* ─► backend (Fastify :3001, interno) ─► PostgreSQL (interno)
CAIXA (HTTPS) ◄─ coletor (Python) ─► PostgreSQL ◄─ analisador (Python: NumPy/SciPy) ◄── fila `job` + NOTIFY cassino_analysis_ready
CloudBeaver http://127.0.0.1:8978 (inspeção SQL, autenticado)      Portainer https://127.0.0.1:9443 (stack separada em infra/portainer)
```

- Somente `127.0.0.1:3000` (app), `:8978` (CloudBeaver) e `:9443` (Portainer, HTTPS) são publicados. Fastify, PostgreSQL e workers só existem na rede Docker.
- Papéis de banco com privilégio mínimo: `cassino_api` só lê (e enfileira jobs/experimentos/sugestões), `cassino_worker` grava dados analíticos, `cassino_inspect` é somente leitura (CloudBeaver).
- Contrato da API: [docs/API.md](docs/API.md).

## Subir / parar

```sh
cp .env.example .env     # preencha 4 senhas longas e independentes (nunca versionar .env)
docker compose config --quiet
docker compose up -d --build --wait
curl -fsS http://127.0.0.1:3000/api/health
```
Parar sem perder dados: `docker compose stop` (ou `down` **sem** `-v`). Reiniciar: `docker compose start`.
Volumes: `postgres_data`, `cloudbeaver_workspace` (Cassino) e `portainer_data` (stack Portainer, independente).

### Migrations (banco existente)
`001-base.sh` roda apenas na primeira inicialização do volume. As demais (`infra/postgres/00N-*.sql`) são aplicadas **uma vez**, como superusuário, em ordem, e registradas em `schema_migration`:
```sh
docker compose exec -T postgres pg_dump -U postgres -Fc cassino > ../cassino-antes.dump   # backup antes
docker compose exec -T postgres psql -U postgres -d cassino -v ON_ERROR_STOP=1 < infra/postgres/00N-nome.sql
```
Estado atual: 002 ingestão · 003 premiações/divergências/jobs · 004 status do coletor · 005 probabilidades/estatística · 006 experimentos/sugestões.

## Operação do dia a dia

- **Coleta**: o `coletor` baixa o histórico oficial (XLSX da CAIXA) a cada 6 h por modalidade, com backoff exponencial em falha e lock por modalidade. Falha da CAIXA não afeta o dashboard. Coleta manual: botão "Atualizar agora" (Administração) ou `docker compose exec coletor python ingest.py quina`.
- **Validação**: dezenas fora do universo, repetidas, datas inválidas → `ingest_quarantine`. Arquivo com >1% de linhas ruins é descartado inteiro. Concurso já validado com dezenas/data diferentes na fonte **não é sobrescrito**: gera `ingest_divergence` (aberta) para decisão: `docker compose exec coletor python ingest.py --resolve ID accept|reject --note "..."`.
- **Análises**: novos dados enfileiram um job `analyze`; o `analisador` recalcula somente janelas cujo conjunto de dados mudou (fingerprint). Backtests e simulações são iniciados pelo dashboard (Modelos / Simulações) e rodam como jobs observáveis.
- **Logs/saúde**: `docker compose logs --tail=100 coletor analisador backend`; estado dos contêineres também no Portainer.
- **Preços das apostas** (`lottery_type.simple_price`) são parâmetros; confirme na CAIXA antes de usar custos (`price_source` registra a origem).

## Consoles administrativos

Inicializados por `python infra/setup_consoles.py`; usuário `cassino-admin`, senhas em `.env.consoles` (ignorado pelo Git; nunca compartilhar).
- **CloudBeaver** http://127.0.0.1:8978 — conexão PostgreSQL host `postgres`, banco `cassino`, usuário `cassino_inspect`. Não use `postgres` para inspeção.
- **Portainer** `docker compose -f infra/portainer/compose.yaml up -d` → https://127.0.0.1:9443 (certificado local autoassinado). A montagem do Docker socket dá controle elevado do Engine: apenas administradores de confiança, apenas loopback. O Compose do repositório é a fonte da verdade; não crie um segundo deploy pelo painel.

## Backup e restauração

```sh
docker compose exec -T postgres pg_dump -U postgres -Fc cassino > cassino.dump      # guardar fora do repositório
# Validar SEMPRE em um PostgreSQL descartável (nunca por cima do banco corrente):
docker run -d --rm --name pg-restore-test -e POSTGRES_PASSWORD=descartavel postgres:17-alpine
docker exec pg-restore-test createdb -U postgres restore_check
docker exec -i pg-restore-test pg_restore -U postgres -d restore_check --no-owner --no-acl < cassino.dump
docker stop pg-restore-test
```
Faça backup separado do workspace do CloudBeaver e dos dados do Portainer antes de manutenções. Nunca use `docker compose down -v`.

## Testes

```sh
bash scripts/test-workers.sh        # workers Python: PostgreSQL descartável (container efêmero na porta 127.0.0.1:55432) + parser, estatística, backtest, simulação
cd backend  && npm test && npm run typecheck
cd frontend && npm test && npm run build
```

## Limites e avisos científicos

- Backtests são **walk-forward**: cada concurso só enxerga o passado; testes de vazamento perturbam o futuro e exigem previsões idênticas. Há sementes registradas e baseline uniforme de mesmo custo; p-values corrigidos por Benjamini–Hochberg; "replicado" exige efeito significativo nas duas metades do período.
- Resultados negativos e inconclusivos têm o mesmo destaque dos positivos. O esperado em sorteios justos é *nenhuma vantagem*.
- Retorno simulado usa rateios nominais históricos e conta o prêmio principal como R$ 0 (piso). O valor esperado de loterias é negativo.
- Random Forest/Boosting não foram implementados: baseline e regressão logística regularizada já cobrem a pergunta (há sinal explorável?).
