# Cassino Launcher — arquitetura proposta (Tarefa 11, fase 1)

Objetivo: um executável Windows que instala, inicia, monitora e administra o Cassino sem exigir conhecimento de Docker, Python, Node ou terminal. Só análise/simulação; nenhuma aposta, nenhum acesso a contas de loteria.

## 1. Escolha da tecnologia

| Opção | Prós | Contras | Decisão |
| --- | --- | --- | --- |
| **C# / .NET 8, self-contained single-file (win-x64)** | Um `.exe` sem runtime externo; WinForms/WPF/WinUI nativos (janela, bandeja, atalhos); `System.Diagnostics.Process`, `HttpClient`, `System.Security.Cryptography` na BCL; bom suporte a assinatura (signtool), MSIX/Inno/WiX; GitHub Actions `windows-latest` traz o SDK | ~70–150 MB self-contained (trimming/ReadyToRun reduz); exige SDK no build (não existe nesta máquina) | **Alvo de produção** |
| .NET Framework 4.8 (`csc.exe` presente no Windows) | Nada a instalar no usuário final (4.8 vem no Win10/11) | C# 5 só pelo csc do sistema; stack legada | Rejeitado (alternativa de contingência) |
| Python + PyInstaller | Reaproveita linguagem do worker; protótipo rápido | Binário maior, falsos positivos de antivírus frequentes, empacotamento frágil; PyInstaller indisponível aqui (sem pip) | Só protótipo |
| Electron / Tauri | UI web; Tauri é pequeno | Mais uma cadeia (Node/Rust), superfície de atualização maior | Rejeitado: não há ganho para um orquestrador de `docker compose` |
| PowerShell/BAT | Zero build | Política de execução, UX ruim, difícil de assinar/testar | Rejeitado |

**Situação real desta máquina:** `dotnet` não está instalado (`dotnet --list-sdks` → comando inexistente) e não instalamos software. Há Python 3.14 (sem pip/PyInstaller), Node 24, Docker 29.8 e Compose 5.5. Por isso o protótipo em `launcher/cassino_launcher/` é **Python (stdlib)** e serve como especificação executável e testada; **nenhum `.exe` foi gerado**. A fase 2 porta a mesma lógica para C# (módulos 1:1: `config`, `envgen`, `system`, `stack`, `backup`, `updates`) e mantém os testes como casos de aceite.

## 2. Módulos e fluxo

```
Cassino-Setup.exe (UI + CLI)
 ├─ config    JSON estrito, valida portas/LAN/projetos
 ├─ envgen    .env com senhas únicas (CSPRNG), idempotente
 ├─ system    Windows x64, Docker, Compose, WSL2, disco, portas
 ├─ stack     docker compose -p cassino … / -p cassino-admin … (arquivos versionados)
 ├─ backup    pg_dump -Fc via docker exec; verificação em contêiner descartável
 └─ updates   GET api.github.com/repos/{repo}/releases/latest (somente leitura)
```

`init` (idempotente): (1) iniciar Docker Desktop se o daemon não responder e aguardar; (2) checar dependências; (3) validar `config.json` e arquivos; (4) gerar `.env` só para variáveis ausentes; (5) `docker compose config -q` das duas stacks; (6) `up -d` da principal e, **separadamente**, da admin; (7) aguardar healthchecks de todos os serviços, confirmar postgres/backend/frontend e `GET /api/health`, abrir `http://localhost:3000`. Falha de qualquer etapa interrompe com mensagem em português e grava `logs/launcher.log`; nada é removido.

## 3. Estrutura de instalação

| Local | Conteúdo | Observação |
| --- | --- | --- |
| `%LOCALAPPDATA%\Programs\Cassino\` | executável do launcher | por usuário, **sem elevação** |
| `%LOCALAPPDATA%\Cassino\app\` | `compose.yaml`, `compose.release.yaml`, `infra/` (portainer, migrations), `.env` | `.env` só aqui, ACL do usuário; nunca no pacote |
| `%LOCALAPPDATA%\Cassino\config.json` | configuração do launcher (sem segredos) | |
| `%LOCALAPPDATA%\Cassino\logs\` | `launcher.log` (rotação) | logs dos contêineres ficam no Docker (json-file 10 MB × 3) |
| `%LOCALAPPDATA%\Cassino\backups\` | `.dump` + `.json` (SHA-256, contagens) | pode ser redirecionado pelo usuário |
| Volumes Docker `cassino_postgres_data`, `cassino_cloudbeaver_workspace`, `cassino-admin_portainer_data` | dados | **dono: Docker**, fora da pasta do app |

`%ProgramData%` foi descartado por exigir administrador e permissões de escrita mais amplas; migra-se para lá apenas se for desejada instalação multiusuário.

## 4. Serviços

Obrigatórios: `postgres`, `backend`, `frontend` (Nginx + SPA + proxy `/api`), `coletor`, `analisador`. Opcionais (config `optional_services`): `cloudbeaver` (`127.0.0.1:8978`) e `portainer` (stack separada `cassino-admin`, `127.0.0.1:9443` HTTPS). Fastify (3001) e PostgreSQL (5432) nunca publicados. Portainer monta o Docker socket (controle elevado do host): o launcher o apresenta como opcional, com aviso, e nunca o expõe fora do loopback. O pipeline funciona sem LLM.

## 5. Imagens e versões (GHCR)

- Pacote de release usa `compose.release.yaml` (modelo em `launcher/templates/`) que substitui `build:` por `ghcr.io/OWNER/cassino-{backend,frontend,workers}:${CASSINO_VERSION}`; a variável é **obrigatória** (`:?`) e sem padrão — **nunca `latest`**. Imagens de terceiros já estão fixas (`postgres:17-alpine`, `cloudbeaver:26.2.3`, `portainer-ce:2.39.8`). Fase 2: registrar digests (`images.lock`) e verificar.
- O launcher compara versão instalada × última release (semver) e apenas informa; atualizar é ação explícita do usuário, precedida de oferta de backup.

## 6. Segredos

`.env` é gerado na primeira execução: 4 senhas de 32 caracteres alfanuméricos (CSPRNG `secrets`; ~190 bits), distintas entre si e entre instalações, gravadas por substituição atômica; valores existentes nunca são sobrescritos e **valores nunca são impressos nem registrados em log** (só os nomes). O pacote e o workflow rejeitam `.env`. Senhas de CloudBeaver/Portainer são criadas pelo usuário na primeira abertura (`infra/setup_consoles.py` já cobre o fluxo atual); fase 2 decide se o launcher guarda isso no Windows Credential Manager (DPAPI).

## 7. Rede e firewall

- Padrão: tudo em `127.0.0.1`.
- LAN: somente com `lan.enabled=true` **e** `lan.acknowledged=true` **e** IP privado informado pelo usuário (sem IP fixo no código; 0.0.0.0, loopback e IP público são rejeitados). Requer que a aplicação exponha apenas leitura/autenticação — hoje o listener LAN é somente GET/HEAD, sem login; autenticação de LAN fica como requisito da fase 2. O launcher **não altera o firewall**: mostra o comando/orientação e deixa a decisão ao usuário.
- Consoles (8978, 9443) nunca seguem para LAN.

## 8. Desinstalação e dados

Remove executável, atalhos, `app/` e imagens opcionais; **não remove volumes** (PostgreSQL, CloudBeaver, Portainer) nem `backups/`. Remover dados é uma ação distinta, com confirmação digitada e backup oferecido; o launcher nunca executa `down -v`. `stop` usa `docker compose stop`.

## 9. Backup e restauração

Backup: `pg_dump -Fc` via `docker exec` (leitura; não bloqueia gravações), arquivo `.dump` + manifesto com SHA-256 e contagem de linhas por tabela. Verificação: contêiner `postgres:17-alpine` descartável (`--network none`, tmpfs, sem volume/porta, senha aleatória própria), `pg_restore --no-owner --exit-on-error`, comparação tabela a tabela, remoção do contêiner. **Restauração sobre o banco ativo não está implementada** (exige parar workers/backend, confirmação e backup prévio — fase 2).

## 10. Distribuição

GitHub Releases: `Cassino-Setup.exe`, `cassino-app-X.Y.Z.zip`, `SHA256SUMS.txt`, `images.lock`. Workflow `.github/workflows/launcher-release.yml` (definido, **não executado**, publicação desabilitada). Assinatura de código (Authenticode/Azure Trusted Signing) é recomendada para evitar SmartScreen; pendente de decisão e de certificado. Modelo de notas: `RELEASE_NOTES_TEMPLATE.md`; guia: `INSTALACAO.md`.

## 11. Riscos e lacunas conhecidos

1. `compose.yaml` fixa portas 3000/8978/9443 e `compose.lan.yaml` fixa um IP; o launcher só aceita portas padrão e exige que `lan.bind_address` conste em `compose.lan.yaml`. Parametrizar exige editar esses arquivos (fora do escopo desta fase).
2. `compose.yaml` usa `build:` (código-fonte); para usuário final é necessário publicar imagens no GHCR (overlay de release criado, validado só com `config -q`).
3. WSL2 é informativo; Hyper-V backend é aceito pelo Docker Desktop.
4. Detecção de "porta em uso pelo próprio Cassino" é heurística (contêineres em execução).
5. Teste em outro computador Windows **não realizado**.
