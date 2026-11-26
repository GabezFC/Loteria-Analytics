# Cassino {{VERSAO}} — notas de versão (modelo)

## Destaques
- ...

## Imagens (GHCR, tags fixas)
`ghcr.io/OWNER/cassino-{backend,frontend,workers}:{{VERSAO}}` — digests no arquivo `images.lock` anexo. Não existe tag `latest`.

## Arquivos
| Arquivo | Descrição |
| --- | --- |
| `Cassino-Setup.exe` | Instalador/launcher (Windows x64) |
| `cassino-app-{{VERSAO}}.zip` | Compose, infraestrutura e migrações (sem segredos) |
| `SHA256SUMS.txt` | Somas SHA-256 de todos os arquivos |

Verifique antes de executar (PowerShell): `Get-FileHash .\Cassino-Setup.exe -Algorithm SHA256` e compare com `SHA256SUMS.txt`.

## Requisitos
Windows 10/11 x64 · Docker Desktop já instalado (com WSL2) · 10 GB livres · portas 3000, 8978 e 9443 livres em 127.0.0.1.

## Atualização
Execute o novo instalador; ele preserva `config.json`, `.env` e os volumes de dados. Faça um backup antes (menu Backup).

## Migrações / mudanças que quebram compatibilidade
- Nenhuma. / Descreva.

## Assinatura de código
Informar se o executável está assinado. Se não estiver, o Windows SmartScreen exibirá aviso.

## Problemas conhecidos
- ...
