# Instalador local do Cassino — Windows x64

O Inno Setup gera um instalador pequeno em relação ao executável autocontido, com atalho no Menu Iniciar e desinstalação registrada por usuário. Ele é necessário só no build. No Windows de destino não é preciso instalar o SDK nem o runtime .NET separadamente.

## Build

Use ISCC do Inno Setup 7.1.1. O [download oficial](https://jrsoftware.org/inno-setup/downloads) pode ser instalado em um diretório gravável pelo usuário com `/PORTABLE=1`. Antes de executá-lo, confira com `Get-AuthenticodeSignature` se `Status` é `Valid` e o publicador é `Pyrsys B.V.`, conforme [instruções do fornecedor](https://jrsoftware.org/inno-setup/downloads/verify). Não é preciso elevar nem editar o PATH; informe o caminho do compilador diretamente.

A partir da raiz do repositório, com o desktop x64 já publicado em `staged/desktop`:

```powershell
$compiler = 'C:\caminho\para\ISCC.exe'
.\launcher\windows\installer\build.ps1 -Iscc $compiler -Version 1.0.0 `
  -Payload .\launcher\windows\staged\desktop -Output .\launcher\windows\staged\release
```

`-Output` é um diretório. O build produz `Cassino-Setup.exe` e `SHA256SUMS.txt` para esse instalador. `-Version` define os metadados do setup, não altera a versão já compilada do launcher. Empacote apenas um desktop confiável e recém-publicado: a lista de arquivos exclui extras, mas não substitui a validação do conteúdo dos arquivos permitidos. São incluídos apenas o executável e os recursos `app` de `integration/stage_assets.py`; não são incluídos Docker Desktop, imagens Docker, PDB, arquivos `.env`, dumps ou logs.

## Instalação e remoção

1. Compare o SHA-256 obtido com `Get-FileHash .\Cassino-Setup.exe -Algorithm SHA256` ao valor em `SHA256SUMS.txt`, recebido de fonte confiável. Os executáveis locais ainda não têm assinatura Authenticode; o checksum verifica integridade, não autenticidade. O Windows pode exibir aviso do SmartScreen. Não desative as proteções do sistema.
2. Execute o setup sem elevação. O destino padrão é `%LOCALAPPDATA%\Programs\Cassino`; abra **Cassino** no Menu Iniciar quando quiser. O setup não inicia o launcher nem o Docker, não usa a rede, não altera o firewall e não modifica o PATH.
3. Para usar a aplicação, prepare Docker Desktop com Docker Compose e as imagens compatíveis, conforme a documentação do launcher. A primeira obtenção das imagens pode exigir internet; imagens previamente carregadas podem ser usadas offline. Reserve espaço adicional para imagens, volumes e backups além dos arquivos do launcher.
4. Feche o launcher antes de reinstalar ou desinstalar. Remova **Cassino** em **Configurações → Aplicativos → Aplicativos instalados**. A remoção preserva `%LOCALAPPDATA%\Cassino` e não inicia, para ou remove contêineres, redes ou volumes Docker. Não há atualização silenciosa, migração nem rollback de dados no instalador: faça backup verificável antes de mudar a versão da stack; restaurar binários não reverte o schema do banco.

## Ensaio isolado

```powershell
.\launcher\windows\installer\test.ps1 -Iscc $compiler `
  -Payload .\launcher\windows\staged\desktop
```

Execute sem elevação. O teste compila um setup exclusivo de fixture com AppId, atalho e diretório separados; não instala o setup de produção. Verifica ausência de extras sintéticos (não usa segredos reais), rejeição de árvore incompleta, checksum, presença e hashes de todos os arquivos instalados, registro HKCU e atalho, execução somente com `--version` a partir de fora do repositório e desinstalação preservando duas sentinelas. Não inicia serviços Docker. Para escolher um diretório descartável existente, use `-Scratch`.
