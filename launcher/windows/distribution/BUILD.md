# Etapa 15 — build local e política de atualização

Na raiz do repositório, com Windows x64, .NET SDK **10.0.404**, Python **3.11+**, CLI `docker compose` e Inno Setup oficial instalado:

```powershell
$build = Join-Path $env:LOCALAPPDATA ('CassinoBuild-' + [Guid]::NewGuid().ToString('N'))
./launcher/windows/distribution/build.ps1 -Iscc 'C:/Program Files (x86)/Inno Setup 6/ISCC.exe' -Version 1.0.0 -BuildRoot $build
```

Ajuste `-Iscc` para a instalação oficial existente; não há download automático. O script exige Authenticode válido do editor do Inno Setup e confere a versão principal pelo compilador. `-Dotnet` e `-Python` podem apontar para executáveis absolutos. Use uma pasta de saída nova e privada. A instalação do SDK e o restore inicial dos packs do .NET podem exigir rede. Os testes não usam um Docker Engine, não baixam imagens e não dependem da stack ativa: Compose é usado apenas para validação de assets com dados fictícios. O próprio instalador não inclui imagens nem Docker Desktop; para rodar a aplicação sem publicação, siga o procedimento local em `../integration/README.md`.

Saídas em `$build`:

- `payload/CassinoLauncher.exe`: WPF `win-x64` autocontido, acompanhado por `payload/app/`.
- `output/Cassino-Setup.exe`: instalador produzido pelo contrato `installer/build.ps1 -Iscc PATH -Version X.Y.Z -Payload PATH -Output PATH`.
- `SHA256SUMS.txt`: caminhos relativos a `$build` e hashes de todos os arquivos entregues, exceto o próprio manifesto.

A lista de caminhos do payload é fechada; nenhum arquivo inesperado é aberto para inspeção. Símbolos, `.env`, credenciais, logs, dumps e fontes da aplicação ficam de fora; `app/lan/bootstrap.py` e as migrations são recursos operacionais explicitamente autorizados. A verificação é por inventário, não uma prova de que arquivos permitidos estão livres de conteúdo sensível, nem uma extração do instalador. Revise alterações nos arquivos autorizados e valide o instalador numa instalação descartável antes de distribuí-lo. O build do Actions não sobe imagens nem retém os artefatos do runner. Para obter os binários, execute o build localmente.

## Atualização manual e autenticada

Nenhum componente desta distribuição baixa ou executa atualizações. A consulta de versão do protótipo Python não autentica uma atualização. `SHA256SUMS.txt` é útil para integridade local, mas sozinho não autentica a origem. Antes de aceitar uma atualização, obtenha a versão aprovada e o certificado público DER (`.cer`) do editor por um canal confiável separado do pacote. Não use o certificado fornecido junto com um download como âncora de confiança. O script não emite certificados nem assina produtos; o operador deve confirmar que o certificado confiável não foi revogado ou substituído. O pin exato não consulta revogação nem valida cadeia ou carimbo de tempo.

O manifesto de atualização (distinto de `SHA256SUMS.txt`) deve conter exatamente duas linhas ASCII, com quebra de linha final:

```text
Cassino-Version: 1.0.0
SHA256: <64 dígitos hexadecimais do Cassino-Setup.exe>
```

O editor deve assinar os bytes exatos em CMS destacado (`.p7s`, DER), incluindo somente um signatário e seu certificado público. Para validar o pacote sem executá-lo:

```powershell
./launcher/windows/distribution/verify-update.ps1 -Manifest './version.txt' -Signature './version.p7s' `
  -TrustedCertificate 'C:/caminho-confiavel/editor.cer' -Installer './Cassino-Setup.exe' -ExpectedVersion 1.0.0
```

Se a validação falhar, se a versão não for a aprovada para avanço, ou se o editor ainda não tiver entregue manifesto autenticado, não instale a atualização como release confiável. Mesmo um manifesto válido não substitui Authenticode no executável nem elimina avisos do SmartScreen. Mantenha os arquivos validados numa pasta privada para que não sejam trocados entre a verificação e a instalação manual.

## Backup e rollback

1. Confirme a instância, versão atual, IDs/digests das imagens e compatibilidade de schema. Preserve o instalador anterior autenticado e a configuração local, sem copiar segredos para a pasta de distribuição.
2. Agende uma janela, bloqueie novas escritas da instância e crie um backup consistente antes das migrations. Verifique o backup e ensaie a restauração numa instância isolada; não apague a anterior nem seus volumes.
3. Instale explicitamente, valide schema, saúde e dados, e só então recoloque a aplicação em serviço. Se falhar, interrompa os escritores da versão nova. Recoloque a versão anterior com o banco anterior intacto ou restaure o backup pré-migration em outro volume validado. Não aponte binários antigos para schema migrado sem compatibilidade comprovada. Retome o tráfego só após validar; trate gravações pós-troca à parte, sem mesclá-las automaticamente.
