# Contrato de integração: recuperação PostgreSQL

```csharp
using CassinoLauncher.Core;

var recovery = new DockerRecovery();
RecoveryResult backup = await recovery.BackupAsync(fullVerifiedPostgresId, chosenDirectory, ct: ct);
RecoveryResult check = await recovery.VerifyAsync(backup.Directory, ct: ct);
```

- `BackupAsync` exige o ID completo (64 hex minúsculos), já verificado pelo chamador como **o serviço `postgres` da instalação atual** (projeto e label de proprietário). Verificação de identidade e escolha de destino são responsabilidades do launcher. Use o contexto local do Docker gravado na configuração, não variáveis de override; a operação fixa seu endpoint até a limpeza. Precisa de acesso ao socket local do PostgreSQL fonte como `postgres`, sem senha no comando.
- `chosenDirectory` já deve existir. `RecoveryResult.Directory` é a nova subpasta que contém `cassino.dump` e `manifest.json`. Ela só ganha o nome final após dump, verificação descartável e limpeza confirmados. `VerifyAsync` recebe essa pasta, não um arquivo, e não exige acesso ao container fonte. Nenhuma API restaura no banco ativo.
- `RecoveryResult.Manifest` expõe `Version`, `Archive`, `SizeBytes`, `Sha256`, `CreatedUtc` e `TableCounts`. As contagens são das tabelas Cassino no banco restaurado, nunca uma leitura posterior da origem. O schema é validado pela execução de DDL/dados via `pg_restore` e pela presença/tipo das tabelas esperadas, não por comparação exaustiva de estrutura. A validação usa `--no-owner --no-privileges`; não valida a criação de papéis nem o provisionamento de permissões de produção.
- As duas operações aceitam `timeout: TimeSpan` (padrão 15 minutos) e `ct`. Trate `InvalidDataException`, `IOException`/`UnauthorizedAccessException`, `TimeoutException`, `OperationCanceledException` e argumentos inválidos. Se não for possível confirmar a limpeza, a exceção inclui somente o label aleatório do recurso descartável para inspeção manual. Cancelar encerra o processo cliente Docker; não garante interrupção instantânea do `pg_dump` remoto.
- A imagem `postgres:17-alpine` deve estar presente localmente; não há pull. A verificação não publica portas, não monta arquivos/volumes do host e usa tmpfs para dados (exige espaço e memória suficientes). A imagem, o daemon e o pacote precisam ser confiáveis: restaurar um dump executa SQL, e SHA-256 sem assinatura detecta corrupção, não autentica autoria. Proteja a pasta com permissões locais; não há criptografia do dump. A pasta `.partial` não é um backup publicado e pode sobrar se o processo ou a máquina forem interrompidos abruptamente.

A recuperação ativa é manual e fica fora desta API: confirmação explícita, backup verificado do estado anterior, parada coordenada dos escritores antes do ponto de corte, restauração separada, validação, troca controlada e plano para retornar ao estado/volume anterior. O backup de uma origem em uso é consistente, mas não contém escritas posteriores ao snapshot.
