# Cassino Launcher para Windows

Launcher WPF/.NET 10 para Windows x64. `CassinoLauncher.exe` é autocontido; o usuário final não instala SDK .NET, Python nem Node. É necessário Docker Desktop com contêineres Linux e Compose 2.24 ou posterior. O launcher não instala o Docker, não altera o firewall e não modifica a stack usada pela raiz do repositório.

## Build e teste local (desenvolvimento)

Execute em `launcher/windows`. Use o SDK oficial fixado em `global.json` (pode chamar `dotnet.exe` pelo caminho absoluto, sem alterar o PATH):

```powershell
dotnet run --project CassinoLauncher.Core.Tests
dotnet run --project CassinoLauncher.Infrastructure.Tests
dotnet publish CassinoLauncher -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o staged/desktop
dotnet publish CassinoLauncher.Cli -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -o staged/cli
python integration/stage_assets.py --output staged/desktop/app
python integration/local_images.py build
python integration/smoke_launcher.py --cli staged/cli/CassinoLauncher.Cli.exe --consoles
Get-FileHash staged/desktop/CassinoLauncher.exe -Algorithm SHA256
```

`local_images.py` só escreve tags locais, sem publicação. Para reutilizar imagens locais verificadas, a opção `tag` exige os IDs completos e imutáveis de backend, frontend e workers. O ensaio usa projetos e portas distintos, induz falha apenas no PostgreSQL do ensaio e deixa os volumes de teste preservados. `--consoles` inclui o Portainer, que monta o socket Docker.

Para homologação sem repositório nem GHCR, leve também `Cassino-Images-linux-amd64.tar`. Confira seu SHA-256 por canal confiável e carregue no Docker Desktop local com `docker image load --input Cassino-Images-linux-amd64.tar`. O tar traz só as três imagens do aplicativo, com tag `0.1.0-local`; PostgreSQL e consoles podem exigir internet na primeira execução. Não use as imagens locais de uma versão para atualizar outra sem verificar a compatibilidade de schema.

`staged/desktop` é um build de desenvolvimento, não um instalador. `app/` precisa acompanhar o executável. Instalações novas usam `%LOCALAPPDATA%\Cassino`, nomes `cassino-launcher` / `cassino-launcher-admin` e portas loopback 3000 (aplicação), 8978 (CloudBeaver) e 9443 (Portainer). Se a stack original estiver rodando nas portas padrão, configure outras portas no `config.json` da nova instalação. Não copie o `.env` de uma instância existente nem reutilize seus volumes por nome. Um nome de instância personalizado deve ter `project` na forma `cassino-<instância>` e `adminProject` igual a `project` mais `-admin`.

A interface abre o dashboard após verificar saúde. `Parar` preserva volumes e deixa o Portainer separado em execução. A coleta pode continuar em segundo plano após a saúde da aplicação ser confirmada. Use a interface de cada console para configurar suas credenciais localmente; não exponha os consoles na LAN.

## Primeiro acesso aos consoles locais

- **Portainer:** no próprio Windows, abra `https://127.0.0.1:9443` (ou a porta configurada), confirme que está falando com a instância local e crie um administrador próprio no assistente. Se o prazo de configuração expirar, reinicie somente o Portainer da instalação correta e repita no host. Não envie tokens de configuração ou senhas pelo chat. O acesso de administrador ao Portainer permite controlar o Docker do host; mantenha-o desligado quando não for necessário (`portainer: false` na configuração para novas instalações).
- **CloudBeaver:** em `http://127.0.0.1:8978` (ou a porta configurada), conclua o assistente inicial com credenciais próprias, sem habilitar acesso anônimo. Para inspeção, use `postgres:5432`, banco `cassino` e a role `cassino_inspect`, nunca a role de administração do banco. A senha de inspeção foi criada no `.env` local protegido; não copie seu conteúdo para logs nem compartilhe o arquivo.
- Para ambos, mantenha credenciais diferentes por instalação e guarde-as em um gerenciador local confiável. O launcher exibe estado dos consoles, mas não importa seus logs brutos, que podem conter tokens de inicialização.

## Backup e recuperação

**Criar backup** pede uma pasta privada existente. O pacote só aparece depois que o dump consistente, o SHA-256 e a restauração descartável tiverem sido validados. **Verificar backup** confere o manifesto e repete a restauração em PostgreSQL sem rede, sem portas publicadas e sem acesso ao banco ativo. Use apenas backups confiáveis; o hash não comprova autoria, e o arquivo não é criptografado pelo launcher. Não inclua backups no instalador ou em repositórios.

Para recuperação ativa, o launcher não faz substituição automática. Com confirmação do operador, programe uma janela de manutenção e identifique os projetos, o volume e a versão em uso. Bloqueie novas operações na interface e pare frontend, backend, coletor e analisador da instância; mantenha PostgreSQL disponível e suspeite de outras conexões com escrita. Crie e valide um backup de segurança desse estado antes de trocar o banco. Confira também o backup a recuperar pela opção de verificação. Restaure em uma segunda instância isolada, com suas próprias credenciais, confira schema, permissões das roles e dados e faça um teste funcional. Só então permita tráfego na instância recuperada. Mantenha a instância e o volume antigos intactos; para reverter, pare os escritores da segunda instância antes de recolocar a anterior em serviço. Não mescle gravações feitas após a troca sem uma estratégia explícita de reconciliação.

## LAN opcional

A distribuição inicia somente em loopback. O overlay HTTPS fica separado e a presença de certificados ou arquivos de configuração não ativa a LAN. Para preparar e habilitar manualmente, siga `app/lan/README.md`, incluindo consentimento para o endereço real, verificação de firewall existente e instalação da CA de confiança em cada cliente. Ao reiniciar a aplicação pelo launcher sem o overlay, a publicação LAN é desativada novamente. Não use o overlay LAN legado com o launcher.
