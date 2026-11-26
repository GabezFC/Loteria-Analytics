# LAN do Launcher Windows — opcional, somente HTTPS

## Integração com a Etapa 13

- No empacotamento, copiar para `app/lan/`: `compose.local.yaml`, `compose.lan.yaml`, `local.conf`, `proxy.inc`, `tls.conf.template`, `bootstrap.py` e este README. Não copiar `compose.test.yaml`, `test_lan.py` nem qualquer conteúdo de runtime do usuário. Não alterar `frontend/nginx.conf` ou usar o `compose.lan.yaml` legado da raiz.
- Para a stack **do app**, usar `app/compose.yaml` e, sempre, `app/lan/compose.local.yaml`, nessa ordem. O segundo substitui `default.conf` no **mesmo** Nginx, sem listener 8080. Sem opt-in, só `127.0.0.1:<porta-app>` → `80`; nenhum arquivo ou credencial LAN é exigido. Portainer continua em sua stack; não aplicar estes overlays à administração.
- Preservar `--project-directory <app> --env-file <home>/.env --env-file <home>/runtime.env -p <projeto-app>` e as verificações de `io.cassino.launcher.owner` do Core para contêineres, volumes e rede. No modo LAN explícito, acrescentar, nessa ordem, `--env-file <pasta-lan>/lan.runtime.env` e o terceiro `-f <app>/lan/compose.lan.yaml`. Todos os `--env-file`/`-f` são opções antes do subcomando. O runtime LAN separado não é sobrescrito por Start. Não deixar que variáveis herdadas (`CASSINO_*`, `COMPOSE_*`, senhas do banco) sobreponham configurações locais. Não registrar o modelo Compose completo (contém senhas do banco).
- A presença de arquivos LAN **não autoriza bind**. O integrador deve manter modo padrão desligado e, antes de publicar em IP real, confirmar com o operador projeto/owner, adaptador ativo, IP, prefixo e porta; validar esses dados, acesso aos arquivos e cadeia TLS corrente. Validar o modelo com `config --quiet` usando Compose ≥ 2.24.4 e conferir no modelo (sem exibi-lo) que as únicas adições são os mounts TLS e o bind solicitado do frontend → 8443, que não há 8080 nem publicação de Fastify/PostgreSQL e que os consoles são loopback. Se qualquer verificação falhar, manter LAN desligada. A porta deve estar disponível no endereço escolhido; uma mudança de IP requer certificado e provisionamento novos.
- Após consentimento específico para o bind real, a ação de alternância pode reconciliar **somente** o frontend do projeto previamente verificado (`up -d --no-deps --wait frontend`), sem parar/recriar o PostgreSQL. Para desativar ou reverter, executar com os dois arquivos base/local, sem o env/overlay LAN, e verificar que a publicação TLS sumiu. Não combinar com o overlay legado nem usar `down -v`. Uma vez ativado, o Docker pode religar o frontend com os binds existentes em restart; para revogar, desativar explicitamente.

## Preparação local (não ativa a LAN)

Pré-requisitos: Python 3.10+, `uv`, OpenSSL 3 no PATH, Docker Desktop com Linux containers para a ativação posterior. No PowerShell, use `Get-NetIPConfiguration` e `Get-NetIPAddress -AddressFamily IPv4` para identificar a interface de confiança e seu prefixo. Use apenas IPv4 privado atribuído à interface LAN real, nunca endereço curinga, adaptador virtual, VPN ou rede convidada. Não crie redirecionamento no roteador. O bootstrap **não** altera firewall; se a política existente não permitir acesso, manter desligado até revisão explícita do administrador (restrição à interface, porta e sub-rede escolhidas).

Emita um certificado de servidor via sua CA de confiança: SAN `IP:<IPv4 escolhido>`, uso `serverAuth`, PEM com o certificado do servidor primeiro e intermediários se houver; chave correspondente, utilizável sem prompt, em local protegido. Instale apenas a CA pública nos clientes por canal confiável e verifique a impressão digital fora de banda; nunca aceite avisos TLS, use `-k` ou distribua a chave da CA/servidor. A validação do bootstrap não instala confiança nos dispositivos. Sem CA confiável para cada cliente, não habilite.

```powershell
# Variáveis são valores escolhidos/verificados pelo operador, não defaults de rede.
uv run --no-project --with bcrypt==5.0.0 python -B ./bootstrap.py --consent `
  --output "$env:LOCALAPPDATA/CassinoLauncher/lan" --ip $ipv4 --port 8443 `
  --cert $fullchain --key $privateKey --ca $caPublic --user lan-operator
```

Execute em terminal interativo; crie a pasta pai privada se necessário. O bootstrap exige um diretório novo, protege com ACL do usuário/SYSTEM (no Windows), valida SAN IP/cadeia/chave e pede confirmação de senha sem eco. Usa bcrypt custo 12 compatível com a imagem Nginx Alpine testada, sem senha em CLI, arquivo de runtime ou logs. Use senha aleatória exclusiva. A saída consiste no hash `htpasswd`, PEMs, config gerada e `lan.runtime.env`; nunca versionar, incluir em artefatos ou compartilhar. Para rotacionar cert/senha, provisione diretório novo e faça a alternância somente com novo consentimento; proteja/descarte a cópia antiga conforme sua política. Basic pode ficar em cache no navegador: revogue/rotacione a senha para invalidá-la; fechar o navegador não é revogação. Não use senha administrativa do host ou banco para LAN.

## Contrato

- LAN: HTTPS TLS ≥ 1.2; Basic em páginas/recursos e operações permitidas; Host fixado à autoridade provisionada. Authorization não é encaminhado ao Fastify. Erros de política podem retornar 403/421 antes do desafio.
- `/api` LAN nega por padrão. GET/HEAD somente de rotas públicas listadas; `/api/admin`, `/api/ingestion/*`, `/api/jobs` e rotas novas/desconhecidas não passam. POST só em `/api/suggestions` e `/api/experiments`, com autenticação, uma `Origin` igual à origem HTTPS configurada e `X-Requested-With: cassino` exato. Não há CORS nem métodos administrativos LAN. Os dados das operações permitidas continuam compartilhados com o app local. A SPA pode mostrar controles administrativos por hash; a API nega a ação independentemente da UI.
- Loopback conserva o app e proxy relativo sem Basic; CloudBeaver e Portainer ficam restritos ao host. Não exponha 80, 3001, 5432 ou consoles na rede. Docker Engine deve ser moderno (≥ 28); não dependa do bind loopback em Engines antigos.

## Validação isolada

Desde a raiz do repo, com as imagens locais da Etapa 13 e PostgreSQL disponíveis:

```text
uv run --no-project --with bcrypt==5.0.0 python -B launcher/windows/lan/test_lan.py
```

Testa Nginx/frontend, Fastify e PostgreSQL reais, com CA e segredos descartáveis, portas efêmeras em `127.0.0.1`, banco em tmpfs e migrações do pacote. Não carrega o `.env` real, não sobe trabalhadores/consoles e só descarta recursos com projeto + owner do teste. O teste confirma criação/enfileiramento e leitura dos dois recursos, não o processamento dos jobs. Testes em celular físico, confiança da CA em clientes da LAN, ativação real e integração final do Core/pacote não fazem parte desta validação; backup/restauração e inicialização dos consoles também estão fora deste recorte.
