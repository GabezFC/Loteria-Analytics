# Homologação do Cassino Launcher 1.0.0

A validação local não substitui um Windows limpo. Não foi disponibilizada outra máquina ou VM autorizada. Não habilitar virtualização, firewall ou LAN real no host atual para preencher esta lacuna.

## Matriz

| Cenário | Estado | Evidência ou condição que falta |
|---|---|---|
| Instalação e atalho | Aprovado localmente em fixture | Setup de teste com AppId e atalho próprios, 16 arquivos conferidos por hash; execução do binário instalado fora da raiz do projeto. Setup final gerado e conferido, não instalado em Windows limpo. |
| Windows limpo x64 sem SDK, Node e Python | Não executado | Exige outra máquina ou VM autorizada. |
| Docker não instalado | Não executado em host limpo | Validar mensagem e ausência de instalação automática. |
| Docker instalado e fechado | Aprovado em simulação | Acionamento único e espera pelo daemon; não foi desligado o Engine em uso. |
| Primeiro uso | Aprovado parcialmente em fixture | Saúde, migrações 002–006, credenciais e serviços; abertura pelo atalho até o dashboard, bootstrap dos consoles, coleta normal e fluxo completo de geração em máquina limpa não exercitados. |
| Segundo uso | Aprovado localmente em fixture | Parada, recriação e reinício com sentinela persistida; reinício do Windows não executado. |
| Rede | Aprovado em fixture | Loopback padrão; seis testes HTTPS com CA de teste e portas efêmeras, incluindo autenticação, autorização e leitura. LAN autenticada em celular físico não testada; correção anterior do 403 confirmada pelo usuário. |
| Falhas | Aprovado parcialmente em fixture | Porta ocupada, falha no PostgreSQL do ensaio, recuperação, timeout e cancelamento. Perda de internet e retomada da coleta não exercitadas. |
| Backup e atualização | Aprovado parcialmente em fixture | Backup restaurado e verificado duas vezes em PostgreSQL descartável. Atualização com manifesto assinado válido, rollback entre versões e recuperação ativa não exercitados. |
| Desinstalação | Aprovado localmente em fixture | Arquivos próprios, atalho e registro removidos; sentinelas preservadas. Validar em máquina limpa com volumes reais da instalação de teste. |

## Evidências reproduzíveis

- Build completo: `distribution/build.ps1`; validou três suítes .NET, 24 testes Python, teste dos Compose e seis testes de inventário.
- Instalação/desinstalação da fixture: `installer/test.ps1 -Iscc <compilador> -Payload <payload>`.
- Ciclo local e recuperação: `integration/smoke_launcher.py --cli <CassinoLauncher.Cli.exe> --consoles`.
- HTTPS em loopback: `uv run --no-project --with bcrypt==5.0.0 python -B launcher/windows/lan/test_lan.py` a partir da raiz do repositório.

## Roteiro em Windows limpo

1. Use Windows 11 x64 sem SDK .NET, Node nem Python, em VM com virtualização aninhada ou outro computador de teste. Reserve espaço para imagens, dados e backup. Confira os hashes do instalador e do tar por canal confiável; o build local não está assinado. Não desative o SmartScreen.
2. Instale `Cassino-Setup.exe` como usuário comum. Abra **Cassino** no Menu Iniciar. Sem Docker, confirme a instrução oficial e que nada foi instalado pelo launcher. Instale Docker Desktop separadamente, com autorização, confirme contêineres Linux e importe `Cassino-Images-linux-amd64.tar` com `docker image load --input Cassino-Images-linux-amd64.tar`. Imagens de terceiros podem requerer internet.
3. Feche o Docker Desktop na máquina dedicada. Reabra o launcher, clique em **Iniciar** e confira tempo de espera, saúde por serviço, dashboard e consoles locais. Inicialize as credenciais dos consoles no host. Aguarde dados oficiais, gere um conjunto experimental, confira histórico/API e persista a evidência SQL usando um identificador não sensível.
4. Verifique somente os bindings previstos em `docker ps` e mantenha LAN desligada. Se houver autorização específica e certificado confiável, teste no celular acesso anônimo, login válido, geração e rejeição administrativa via HTTPS. Não aceite avisos de certificado.
5. Teste porta ocupada, falha de serviço, ciclo parar/iniciar, reinício do Windows e interrupção/retomada de rede. Não toque em outra stack. Crie e verifique backup em destino isolado. Se houver uma segunda versão autenticada, ensaie atualização e rollback com janela, backups e volumes preservados.
6. Desinstale via Configurações do Windows. Confirme que atalho e binários saíram e que configuração, backups e volumes ficaram. Registre resultados e horários sem incluir senhas, dumps ou logs brutos.
