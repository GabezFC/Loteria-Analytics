# Instalação do Cassino no Windows (guia do usuário)

> Estado: **protótipo**. O instalador `Cassino-Setup.exe` ainda não existe; este guia descreve o fluxo-alvo e, entre colchetes, o equivalente do protótipo.

## Antes de começar
1. Windows 10/11 de 64 bits.
2. Instale o **Docker Desktop** (docker.com) e conclua a configuração inicial. O Cassino **não** instala nem distribui o Docker.
3. 10 GB livres. Nenhum programa usando as portas 3000, 8978 e 9443.

## Instalar
1. Baixe `Cassino-Setup.exe` e `SHA256SUMS.txt` da página de Releases do projeto.
2. Confira o hash: `Get-FileHash .\Cassino-Setup.exe -Algorithm SHA256` deve coincidir com o do arquivo de somas.
3. Execute. O assistente verifica o computador, inicia o Docker Desktop se necessário, cria suas senhas (únicas, ficam só neste computador), baixa as imagens e abre http://localhost:3000.
   [protótipo: `python -m cassino_launcher init`]

## Uso diário
Iniciar, parar, reiniciar, status, logs, backup e verificação de atualização no próprio aplicativo. [protótipo: `init/stop/restart/status/logs/backup/verify-backup/update-check`]

## Painéis administrativos (somente neste computador)
- Banco de dados (CloudBeaver): http://localhost:8978
- Docker (Portainer): https://localhost:9443 (certificado autoassinado: o aviso do navegador é esperado)

## Acesso pela rede local (opcional, desligado por padrão)
Só com habilitação explícita no `config.json` (`lan.enabled`, `lan.acknowledged`, `lan.bind_address` com o IP privado deste computador). O Cassino **não altera o firewall**; liberar a porta é decisão sua.

## Desinstalar
Remove programa, atalhos e imagens opcionais. **Os dados (volumes do PostgreSQL) são mantidos**; apagá-los exige ação separada e confirmação digitada. Faça backup antes.

## Problemas
Logs em `%LOCALAPPDATA%\Cassino\logs`. Windows SmartScreen pode avisar se o executável não estiver assinado.
