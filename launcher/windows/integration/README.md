# Etapa 13 — recursos e integração no Windows

Execute os comandos a partir da raiz do repositório. Python 3.10+ é ferramenta de build/teste; não é dependência do launcher distribuído.

## Preparar o pacote e validar offline

```powershell
python -B launcher/windows/integration/stage_assets.py
python -B launcher/windows/integration/test_assets.py
```

`stage_assets.py` gera `launcher/windows/app/compose.yaml`, `compose.admin.yaml`, `infra/postgres/001-base.sh` e os `infra/postgres/*.sql` canônicos, sem copiar `.env`. Esses artefatos são ignorados pelo Git. Rode o staging em cada build limpo antes de copiar `app/` ao lado do EXE, ou use `stage_assets.py --output <diretório-do-pacote>/app` para gerar diretamente no destino. Mantenha o caminho relativo `app/infra/postgres/`. Os testes validam ambos os Compose com `config --quiet`, arquivos temporários de valores fictícios e sem Engine. O script de base preserva LF e é o único mount de inicialização; o Core envia `002` a `006` em ordem via `psql`. `002` não grava marcador: `003` registra ambos. O healthcheck de PostgreSQL usa TCP e consulta a tabela `lottery_type` criada pelo script base; não aguarda as migrations.

O Core fornece `--env-file <home>/.env --env-file <home>/runtime.env`: o primeiro tem somente os quatro segredos gerados pelo launcher; o segundo contém o owner e as três portas. As duas stacks marcam contêineres, volumes e redes com `io.cassino.launcher.owner`. Não sobrescreva as variáveis `CASSINO_LAUNCHER_OWNER`, `CASSINO_*_PORT` nem `COMPOSE_PROJECT_NAME` no ambiente ao operar manualmente: o ambiente prevalece sobre o arquivo. PostgreSQL, Fastify e workers não publicam portas. CloudBeaver é iniciado explicitamente quando habilitado; Portainer tem projeto separado, acesso HTTPS apenas local e Docker socket privilegiado.

## Imagens locais

```powershell
python -B launcher/windows/integration/local_images.py build
# Alternativa para imagens locais cuja procedência você verificou:
python -B launcher/windows/integration/local_images.py tag --backend <sha256:ID> --frontend <sha256:ID> --workers <sha256:ID>
```

O helper não sobe stacks. `build` usa os Dockerfiles atuais das três pastas canônicas e pode baixar dependências. `tag` exige IDs completos de imagens locais `linux/amd64`; o ID por si só não comprova procedência. Ambos gravam apenas as tags `cassino-launcher/{backend,frontend,workers}:0.1.0-local`. Os Compose do aplicativo só usam imagens locais para esses componentes (`pull_policy: never`), com overrides opcionais `CASSINO_BACKEND_IMAGE`, `CASSINO_FRONTEND_IMAGE` e `CASSINO_WORKERS_IMAGE`. As imagens de terceiros mantêm as referências do repositório e podem exigir pull se ausentes. Use `--context default` *antes* de `build`/`tag` se necessário; o contexto padrão do helper é `desktop-linux`.

## Executar o smoke test isolado

Com Docker Desktop já ativo em modo Linux, imagens locais prontas e o CLI compilado/publicado:

```powershell
python -B launcher/windows/integration/smoke_launcher.py --cli 'CAMINHO\CassinoLauncher.Cli.exe'
```

O teste usa `--home <temp> --assets <temp>`, nomes aleatórios `cassino-it-*` e três portas de loopback escolhidas pelo SO. Há uma pequena janela entre liberar as portas de teste e o Docker fazer o bind; em conflito externo, rode novamente. O teste usa os workers reais e adia somente a coleta externa no Compose temporário. Verifica rejeição da porta ocupada, status e logs do CLI, saúde por serviço e via Nginx, migrations/seeds, degradação após parar **só** o PostgreSQL da fixture e `stop`/`start` com recriação de contêineres e persistência de uma linha no banco. Adicione `--consoles` apenas se quiser iniciar CloudBeaver e Portainer; nesse modo o teste confirma que parar a aplicação não para o Portainer. Não desliga o Engine para simular indisponibilidade: faça esse caso com runner simulado ou numa máquina dedicada, nunca em um host com stacks ativas.

A limpeza usa `compose down` exclusivamente nos projetos da fixture; não usa `down -v`, prune ou remoção de volumes. As pastas temporárias (inclusive segredos descartáveis) e os volumes são preservados; não publique essas pastas. Se a execução for interrompida, use os nomes e caminhos impressos para limpar apenas os projetos daquele teste, com os dois arquivos de ambiente e sem `-v`.
