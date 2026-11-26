using System.Collections.ObjectModel;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace CassinoLauncher.Core;

public sealed record RecoveryManifest(int Version, string Archive, long SizeBytes, string Sha256,
    DateTimeOffset CreatedUtc, IReadOnlyDictionary<string, long> TableCounts);

public sealed record RecoveryResult(string Directory, RecoveryManifest Manifest);

/// <summary>Backs up Cassino and verifies trusted bundles on a disposable local PostgreSQL, never on the active database.</summary>
public sealed class DockerRecovery
{
    private const string Archive = "cassino.dump";
    private const string ManifestFile = "manifest.json";
    private const int MaxMetadataBytes = 16 * 1024;
    private const string Image = "postgres:17-alpine";
    private const string Socket = "/var/run/postgresql";
    private const string Database = "cassino";
    private static readonly string[] PgEnv = ["env", "-i", "PATH=/usr/local/bin:/usr/bin:/bin"];
    // Docker CLI can inject proxy URLs (including credentials) from its configuration into new containers.
    private static readonly string[] NoProxyEnv = new[] { "HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "ALL_PROXY", "NO_PROXY" }
        .SelectMany(name => new[] { "--env=" + name + "=", "--env=" + name.ToLowerInvariant() + "=" }).ToArray();
    private static readonly TimeSpan DefaultTimeout = TimeSpan.FromMinutes(15);
    private static readonly TimeSpan ControlTimeout = TimeSpan.FromSeconds(15);
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = false, NumberHandling = JsonNumberHandling.Strict,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow, AllowDuplicateProperties = false,
        RespectRequiredConstructorParameters = true, WriteIndented = true
    };
    private static readonly string[] Tables = ["lottery_type", "lottery_draw", "draw_number", "ingest_run",
        "ingest_draw_change", "schema_migration", "draw_prize_tier", "draw_extra", "ingest_quarantine",
        "ingest_divergence", "job", "collector_status", "probability_table", "analysis_run", "number_stat",
        "combination_stat", "analysis_result", "experiment", "experiment_result", "suggestion_set", "suggestion"];
    // These identifiers are constants, not taken from the manifest. Require ordinary Cassino tables, not views.
    private static readonly string CountSql = "SELECT json_object_agg(n, c) FROM (" + string.Join(" UNION ALL ", Tables.Select(
        t => $"SELECT '{t}' AS n, (SELECT count(*) FROM ONLY public.\"{t}\") AS c WHERE " +
             $"(SELECT relkind FROM pg_catalog.pg_class WHERE oid = 'public.\"{t}\"'::regclass) = 'r'")) + ") AS counts;";
    private readonly IRecoveryProcess process;

    public DockerRecovery() : this(new RecoveryProcess()) { }
    internal DockerRecovery(IRecoveryProcess process) => this.process = process;

    /// <summary>Caller must verify the full container ID belongs to the launcher’s postgres service on the selected local Docker context.</summary>
    /// <param name="verifiedContainerId">Full 64-character lowercase Docker container ID, not a service or container name.</param>
    /// <param name="destinationDirectory">Existing user-selected directory. A new, uniquely named bundle is published inside it.</param>
    /// <param name="timeout">Overall operation budget, excluding bounded cleanup; defaults to 15 minutes.</param>
    /// <param name="ct">Cancellation token.</param>
    public Task<RecoveryResult> BackupAsync(string verifiedContainerId, string destinationDirectory,
        TimeSpan? timeout = null, CancellationToken ct = default)
    {
        if (!IsHex(verifiedContainerId)) throw new ArgumentException("Informe o ID completo do container PostgreSQL verificado.", nameof(verifiedContainerId));
        return WithDeadlineAsync(token => BackupCoreAsync(verifiedContainerId, destinationDirectory, token), timeout, ct);
    }

    /// <summary>Validate the manifest and archive, then restore and compare counts again. Only accept trusted bundles.</summary>
    public Task<RecoveryResult> VerifyAsync(string backupDirectory, TimeSpan? timeout = null, CancellationToken ct = default) =>
        WithDeadlineAsync(token => VerifyCoreAsync(backupDirectory, token), timeout, ct);

    private async Task<RecoveryResult> BackupCoreAsync(string sourceId, string destination, CancellationToken ct)
    {
        var parent = ExistingDirectory(destination);
        var endpoint = await ResolveEndpointAsync(ct).ConfigureAwait(false);
        var created = DateTimeOffset.UtcNow;
        var nonce = Guid.NewGuid().ToString("N");
        var staging = Path.Combine(parent, $".cassino-recovery-{nonce}.partial");
        var final = Path.Combine(parent, $"cassino-{created:yyyyMMdd-HHmmss}-{nonce}");
        Directory.CreateDirectory(staging);
        try
        {
            var archivePath = Path.Combine(staging, Archive);
            await using (var output = Open(archivePath, FileMode.CreateNew))
            {
                await MustAsync(endpoint, "criar o dump", ["exec", sourceId, .. PgEnv, "pg_dump", "--format=custom",
                    "--no-password", "--host=" + Socket, "--username=postgres", "--dbname=" + Database], ct,
                    output: output).ConfigureAwait(false);
                await output.FlushAsync(ct).ConfigureAwait(false);
                output.Flush(flushToDisk: true);
            }
            RecoveryManifest manifest;
            await using (var archive = Open(archivePath, FileMode.Open))
            {
                var sha = await ArchiveHashAsync(archive, ct).ConfigureAwait(false);
                var counts = await RestoreAsync(endpoint, archive, sourceId, ct).ConfigureAwait(false);
                manifest = new(1, Archive, archive.Length, sha, created, counts);
            }
            await using (var file = Open(Path.Combine(staging, ManifestFile), FileMode.CreateNew))
            {
                await JsonSerializer.SerializeAsync(file, manifest, Json, ct).ConfigureAwait(false);
                await file.FlushAsync(ct).ConfigureAwait(false);
                file.Flush(flushToDisk: true);
            }
            ct.ThrowIfCancellationRequested();
            Directory.Move(staging, final);
            return new(final, manifest);
        }
        finally
        {
            if (Directory.Exists(staging)) Directory.Delete(staging, recursive: true);
        }
    }

    private async Task<RecoveryResult> VerifyCoreAsync(string directory, CancellationToken ct)
    {
        var folder = ExistingDirectory(directory);
        RecoveryManifest manifest;
        try
        {
            await using var file = Open(Path.Combine(folder, ManifestFile), FileMode.Open);
            if (file.Length is <= 0 or > MaxMetadataBytes) throw InvalidManifest();
            using var metadata = new MetadataBuffer();
            await file.CopyToAsync(metadata, ct).ConfigureAwait(false);
            manifest = JsonSerializer.Deserialize<RecoveryManifest>(metadata.ToArray(), Json) ?? throw InvalidManifest();
        }
        catch (JsonException) { throw InvalidManifest(); }
        catch (FileNotFoundException) { throw InvalidManifest(); }

        if (manifest.Version != 1 || manifest.Archive != Archive || manifest.SizeBytes < 6 || !IsHex(manifest.Sha256) ||
            manifest.CreatedUtc == default || manifest.CreatedUtc.Offset != TimeSpan.Zero || !ValidCounts(manifest.TableCounts))
            throw InvalidManifest();

        await using var archive = Open(Path.Combine(folder, Archive), FileMode.Open);
        if (archive.Length != manifest.SizeBytes || await ArchiveHashAsync(archive, ct).ConfigureAwait(false) != manifest.Sha256)
            throw new InvalidDataException("O tamanho ou SHA-256 do dump diverge do manifesto.");
        var endpoint = await ResolveEndpointAsync(ct).ConfigureAwait(false);
        var actual = await RestoreAsync(endpoint, archive, null, ct).ConfigureAwait(false);
        if (Tables.Any(t => actual[t] != manifest.TableCounts[t]))
            throw new InvalidDataException("As contagens do PostgreSQL restaurado divergem do manifesto.");
        return new(folder, manifest with { TableCounts = actual });
    }

    private async Task<IReadOnlyDictionary<string, long>> RestoreAsync(string endpoint, FileStream archive,
        string? sourceId, CancellationToken ct)
    {
        var label = $"io.cassino.launcher.recovery={Guid.NewGuid():N}";
        try
        {
            var id = (await RequiredTextAsync(endpoint, "iniciar o PostgreSQL descartável", ["run", "--detach", "--rm",
                "--pull=never", "--network=none", "--log-driver=none", "--security-opt=no-new-privileges:true",
                "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,noexec", "--label=" + label,
                .. NoProxyEnv, "--env=POSTGRES_HOST_AUTH_METHOD=trust", "--env=POSTGRES_DB=" + Database,
                Image, "postgres", "-c", "listen_addresses=127.0.0.1"], ct).ConfigureAwait(false)).Trim();
            if (!IsHex(id) || id == sourceId) throw new IOException("O Docker não retornou um ID descartável válido.");

            // The image's bootstrap server is socket-only; wait for the final server on disposable loopback.
            using var ready = CancellationTokenSource.CreateLinkedTokenSource(ct);
            ready.CancelAfter(TimeSpan.FromSeconds(60));
            try
            {
                while (await process.RunAsync(["--host", endpoint, "exec", id, .. PgEnv, "pg_isready", "-q",
                    "-h", "127.0.0.1", "-U", "postgres", "-d", Database, "-t", "1"], ControlTimeout,
                    ready.Token, Stream.Null).ConfigureAwait(false) != 0)
                    await Task.Delay(300, ready.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            { throw new TimeoutException("O PostgreSQL descartável não ficou pronto."); }

            archive.Position = 0;
            await MustAsync(endpoint, "restaurar o dump no PostgreSQL descartável", ["exec", "-i", id, .. PgEnv,
                "pg_restore", "--exit-on-error", "--single-transaction", "--no-owner", "--no-privileges",
                "--no-password", "--host=" + Socket, "--username=postgres", "--dbname=" + Database], ct,
                input: archive).ConfigureAwait(false);
            var text = await RequiredTextAsync(endpoint, "conferir o schema e contar as tabelas restauradas", ["exec", id,
                .. PgEnv, "psql", "-X", "-Atqw", "-h", Socket, "-U", "postgres", "-d", Database,
                "-v", "ON_ERROR_STOP=1", "-c", CountSql], ct).ConfigureAwait(false);
            try
            {
                var counts = JsonSerializer.Deserialize<Dictionary<string, long>>(text, Json);
                if (counts is null || !ValidCounts(counts)) throw InvalidSchema();
                return new ReadOnlyDictionary<string, long>(counts);
            }
            catch (JsonException) { throw InvalidSchema(); }
        }
        finally
        {
            // Look up only this invocation's random label, including if docker run was interrupted before emitting its ID.
            using var cleanup = new CancellationTokenSource(TimeSpan.FromSeconds(20));
            try
            {
                foreach (var id in await FindDisposablesAsync(endpoint, label, cleanup.Token).ConfigureAwait(false))
                {
                    if (!IsHex(id) || id == sourceId) throw new IOException();
                    var code = await process.RunAsync(["--host", endpoint, "container", "rm", "--force", "--volumes", id],
                        ControlTimeout, cleanup.Token, Stream.Null).ConfigureAwait(false);
                    if (code != 0 && (await FindDisposablesAsync(endpoint, label, cleanup.Token).ConfigureAwait(false)).Contains(id))
                        throw new IOException();
                }
            }
            catch (Exception ex) when (ex is IOException or TimeoutException or OperationCanceledException)
            { throw new IOException($"Não foi possível confirmar a limpeza do PostgreSQL descartável (label {label})."); }
        }
    }

    private async Task<string[]> FindDisposablesAsync(string endpoint, string label, CancellationToken ct) =>
        (await RequiredTextAsync(endpoint, "localizar o PostgreSQL descartável", ["container", "ls", "-aq", "--no-trunc",
            "--filter", "label=" + label], ct).ConfigureAwait(false)).Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

    private async Task<string> ResolveEndpointAsync(CancellationToken ct)
    {
        var context = (await RequiredTextAsync(null, "identificar o contexto do Docker", ["context", "show"], ct).ConfigureAwait(false)).Trim();
        if (context.Length is < 1 or > 128 || !char.IsAsciiLetterOrDigit(context[0]) ||
            context.Any(c => !char.IsAsciiLetterOrDigit(c) && c is not ('-' or '_' or '.')))
            throw new IOException("Contexto Docker inválido.");
        var endpoint = (await RequiredTextAsync(null, "identificar o endpoint do Docker",
            ["context", "inspect", context, "--format", "{{ (index .Endpoints \"docker\").Host }}"], ct).ConfigureAwait(false)).Trim();
        if (endpoint.Any(char.IsControl) || !(OperatingSystem.IsWindows()
                ? endpoint.StartsWith("npipe:////./pipe/", StringComparison.OrdinalIgnoreCase)
                : endpoint.StartsWith("unix:///", StringComparison.Ordinal)))
            throw new IOException("A recuperação exige um endpoint Docker local (named pipe ou socket Unix).");
        return endpoint;
    }

    private async Task<string> RequiredTextAsync(string? endpoint, string phase, string[] args, CancellationToken ct)
    {
        using var buffer = new MetadataBuffer();
        await MustAsync(endpoint, phase, args, ct, buffer, timeout: ControlTimeout).ConfigureAwait(false);
        return Encoding.UTF8.GetString(buffer.ToArray());
    }

    private async Task MustAsync(string? endpoint, string phase, string[] args, CancellationToken ct,
        Stream? output = null, Stream? input = null, TimeSpan? timeout = null)
    {
        var code = await process.RunAsync(endpoint is null ? args : ["--host", endpoint, .. args],
            timeout ?? MaxTimeout, ct, output ?? Stream.Null, input).ConfigureAwait(false);
        if (code != 0) throw new IOException($"Falha ao {phase} (Docker código {code}).");
    }

    private static readonly TimeSpan MaxTimeout = TimeSpan.FromMilliseconds(uint.MaxValue - 1L);

    private static async Task<T> WithDeadlineAsync<T>(Func<CancellationToken, Task<T>> action, TimeSpan? timeout, CancellationToken ct)
    {
        var budget = timeout ?? DefaultTimeout;
        if (budget <= TimeSpan.Zero || budget > MaxTimeout) throw new ArgumentOutOfRangeException(nameof(timeout));
        ct.ThrowIfCancellationRequested();
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(budget);
        try { return await action(deadline.Token).ConfigureAwait(false); }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        { throw new TimeoutException("Tempo limite excedido na recuperação PostgreSQL."); }
    }

    private static string ExistingDirectory(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        var full = Path.GetFullPath(path);
        if (!Directory.Exists(full)) throw new DirectoryNotFoundException("A pasta de recuperação não existe ou está inacessível.");
        return full;
    }

    private static FileStream Open(string path, FileMode mode)
    {
        if (mode == FileMode.Open && (File.GetAttributes(path) & (FileAttributes.ReparsePoint | FileAttributes.Directory)) != 0)
            throw new InvalidDataException("O pacote deve conter arquivos comuns, sem links.");
        return new(path, mode, mode == FileMode.Open ? FileAccess.Read : FileAccess.Write,
            mode == FileMode.Open ? FileShare.Read : FileShare.None, 65536, FileOptions.Asynchronous | FileOptions.SequentialScan);
    }

    private static async Task<string> ArchiveHashAsync(FileStream archive, CancellationToken ct)
    {
        var header = new byte[5];
        if (archive.Length < 6 || await archive.ReadAtLeastAsync(header, header.Length, false, ct).ConfigureAwait(false) != header.Length ||
            !header.AsSpan().SequenceEqual("PGDMP"u8))
            throw new InvalidDataException("O dump não é um arquivo PostgreSQL de formato custom.");
        archive.Position = 0;
        return Convert.ToHexStringLower(await SHA256.HashDataAsync(archive, ct).ConfigureAwait(false));
    }

    private static bool IsHex(string? value) => value is { Length: 64 } && value.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');
    private static bool ValidCounts(IReadOnlyDictionary<string, long>? counts) => counts is not null &&
        counts.Count == Tables.Length && Tables.All(t => counts.TryGetValue(t, out var count) && count >= 0);
    private static InvalidDataException InvalidManifest() => new("Manifesto de backup ausente ou inválido.");
    private static InvalidDataException InvalidSchema() => new("O PostgreSQL restaurado não contém o conjunto esperado de tabelas Cassino.");

    private sealed class MetadataBuffer : MemoryStream
    {
        public override void Write(byte[] buffer, int offset, int count)
        {
            Check(count);
            base.Write(buffer, offset, count);
        }

        public override void Write(ReadOnlySpan<byte> buffer)
        {
            Check(buffer.Length);
            base.Write(buffer);
        }

        private void Check(int count)
        {
            if (Position + count > MaxMetadataBytes) throw new IOException("Metadados de recuperação excederam o limite.");
        }
    }
}
