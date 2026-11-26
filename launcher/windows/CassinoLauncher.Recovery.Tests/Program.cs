using CassinoLauncher.Core;
using System.Text.Json;
using System.Text.Json.Nodes;

const string SourceId = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const string VerifyId = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
var endpoint = OperatingSystem.IsWindows() ? "npipe:////./pipe/dockerDesktopLinuxEngine" : "unix:///var/run/docker.sock";
var root = Directory.CreateTempSubdirectory("cassino-recovery-tests-");
try
{
    var docker = new FakeDocker(endpoint, SourceId, VerifyId);
    var recovery = new DockerRecovery(docker);
    var backup = await recovery.BackupAsync(SourceId, root.FullName);
    Check(Path.GetDirectoryName(backup.Directory) == root.FullName, "bundle in selected directory");
    Check(root.GetDirectories().Length == 1, "no staging directory left");
    Check(backup.Manifest.Sha256 == Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(FakeDocker.Dump)), "SHA-256 matches original bytes");
    Check(backup.Manifest.TableCounts["lottery_draw"] == 7, "counts from isolated restore");
    Check(docker.Dumps == 1 && docker.Restores == 1 && docker.Cleanups == 1, "one dump, one isolated restore and cleanup");
    var verified = await recovery.VerifyAsync(backup.Directory);
    Check(verified.Manifest.TableCounts["lottery_draw"] == 7 && docker.Dumps == 1 && docker.Restores == 2, "repeat verification without live source");

    var manifest = Path.Combine(backup.Directory, "manifest.json");
    var original = await File.ReadAllTextAsync(manifest);
    async Task InvalidManifest(Action<JsonObject> change)
    {
        var json = JsonNode.Parse(original)!.AsObject();
        change(json);
        await File.WriteAllTextAsync(manifest, json.ToJsonString());
        var commands = docker.Commands;
        await Reject<InvalidDataException>(() => recovery.VerifyAsync(backup.Directory));
        Check(commands == docker.Commands, "invalid manifest rejected before Docker");
    }
    await InvalidManifest(json => json["version"] = 2);
    await InvalidManifest(json => json["archive"] = "../cassino.dump");
    await InvalidManifest(json => json["sha256"] = new string('f', 64));
    await InvalidManifest(json => json["sha256"] = "broken");
    await InvalidManifest(json => json["sizeBytes"] = 0);
    await InvalidManifest(json => json["tableCounts"]!["lottery_draw"] = -1);
    await InvalidManifest(json => json["tableCounts"]!.AsObject().Remove("lottery_draw"));
    await InvalidManifest(json => json["unknown"] = true);
    await File.WriteAllTextAsync(manifest, original.TrimEnd()[..^1] + ",\"version\":1}");
    await Reject<InvalidDataException>(() => recovery.VerifyAsync(backup.Directory));
    await File.WriteAllTextAsync(manifest, original.Replace("\"lottery_draw\": 7", "\"lottery_draw\": 7, \"lottery_draw\": 7"));
    await Reject<InvalidDataException>(() => recovery.VerifyAsync(backup.Directory));

    var wrongCounts = JsonNode.Parse(original)!.AsObject();
    wrongCounts["tableCounts"]!["lottery_draw"] = 8;
    await File.WriteAllTextAsync(manifest, wrongCounts.ToJsonString());
    var before = docker.Cleanups;
    await Reject<InvalidDataException>(() => recovery.VerifyAsync(backup.Directory));
    Check(docker.Cleanups == before + 1, "mismatched restored counts still clean up");
    await File.WriteAllTextAsync(manifest, original);
    var tampered = FakeDocker.Dump.ToArray();
    tampered[^1] ^= 1;
    await File.WriteAllBytesAsync(Path.Combine(backup.Directory, "cassino.dump"), tampered);
    var commandsBefore = docker.Commands;
    await Reject<InvalidDataException>(() => recovery.VerifyAsync(backup.Directory));
    Check(commandsBefore == docker.Commands, "changed dump rejected before Docker");

    await Reject<ArgumentException>(() => recovery.BackupAsync("postgres", root.FullName));
    await Reject<OperationCanceledException>(() => recovery.BackupAsync(SourceId, root.FullName, ct: new(true)));
    Check(commandsBefore == docker.Commands, "invalid or cancelled source never invoked");
    docker.FailRestore = true;
    before = docker.Cleanups;
    await Reject<IOException>(() => recovery.BackupAsync(SourceId, root.FullName));
    Check(docker.Cleanups == before + 1 && root.GetDirectories().Length == 1, "failed backup neither publishes nor leaves staging");
    docker.FailRestore = false;
    using var cancel = new CancellationTokenSource();
    docker.RestoreStarted = cancel.Cancel;
    before = docker.Cleanups;
    await Reject<OperationCanceledException>(() => recovery.BackupAsync(SourceId, root.FullName, ct: cancel.Token));
    Check(docker.Cleanups == before + 1 && root.GetDirectories().Length == 1, "cancellation still cleans disposable and staging");
    docker.RestoreStarted = null;
    docker.EndpointOverride = "tcp://example.invalid:2375";
    var dumps = docker.Dumps;
    await Reject<IOException>(() => recovery.BackupAsync(SourceId, root.FullName));
    Check(docker.Dumps == dumps, "non-local contexts refused before dump");
    Console.WriteLine("Recovery: backup, verificação e manifestos inválidos OK.");
}
finally { root.Delete(recursive: true); }

static void Check(bool condition, string name)
{
    if (!condition) throw new Exception(name);
}

static async Task Reject<T>(Func<Task> action) where T : Exception
{
    try { await action(); }
    catch (T) { return; }
    throw new Exception($"Expected {typeof(T).Name}");
}

sealed class FakeDocker(string endpoint, string source, string disposable) : IRecoveryProcess
{
    internal static readonly byte[] Dump = [80, 71, 68, 77, 80, 0, 255, 13, 10, 1];
    internal int Dumps, Restores, Cleanups, Commands;
    internal bool FailRestore;
    internal Action? RestoreStarted;
    internal string? EndpointOverride;
    private string? ownedLabel;
    public async Task<int> RunAsync(string[] args, TimeSpan timeout, CancellationToken ct, Stream output, Stream? input = null)
    {
        ++Commands;
        string? response = null;
        if (args is ["context", "show"]) response = "desktop-linux\n";
        else if (args is ["context", "inspect", "desktop-linux", "--format", _]) response = (EndpointOverride ?? endpoint) + "\n";
        else if (args is ["--host", var host, .. var cmd] && host == endpoint)
        {
            if (cmd[0] == "run")
            {
                string[] required = ["--pull=never", "--network=none", "--rm", "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,noexec", "--env=POSTGRES_HOST_AUTH_METHOD=trust", "postgres:17-alpine"];
                if (required.Any(x => !cmd.Contains(x)) || cmd.Any(x => x.StartsWith("--publish") || x.StartsWith("--mount") || x.StartsWith("--volume")))
                    throw new Exception("Disposable must be isolated without host binds or published ports");
                ownedLabel = cmd.Single(x => x.StartsWith("--label="))[8..];
                response = disposable + "\n";
            }
            else if (cmd.Contains("pg_dump"))
            {
                if (cmd[0] != "exec" || cmd[1] != source || !cmd.Contains("--format=custom")) throw new Exception("wrong dump invocation");
                ++Dumps;
                await output.WriteAsync(Dump, ct);
            }
            else if (cmd.Contains("pg_restore"))
            {
                if (cmd is not ["exec", "-i", var target, ..] || target != disposable || !cmd.Contains("--exit-on-error")) throw new Exception("wrong restore invocation");
                RestoreStarted?.Invoke();
                ct.ThrowIfCancellationRequested();
                using var bytes = new MemoryStream();
                await input!.CopyToAsync(bytes, ct);
                if (!Dump.SequenceEqual(bytes.ToArray())) throw new Exception("binary stream corrupted");
                ++Restores;
                if (FailRestore) return 1;
            }
            else if (cmd.Contains("pg_isready") && cmd.Contains(disposable)) { }
            else if (cmd.Contains("psql") && cmd.Contains(disposable))
                response = JsonSerializer.Serialize(new Dictionary<string, long> {
                    ["lottery_type"] = 3, ["lottery_draw"] = 7, ["draw_number"] = 42, ["ingest_run"] = 0,
                    ["ingest_draw_change"] = 0, ["schema_migration"] = 5, ["draw_prize_tier"] = 0,
                    ["draw_extra"] = 0, ["ingest_quarantine"] = 0, ["ingest_divergence"] = 0, ["job"] = 0,
                    ["collector_status"] = 0, ["probability_table"] = 0, ["analysis_run"] = 0,
                    ["number_stat"] = 0, ["combination_stat"] = 0, ["analysis_result"] = 0,
                    ["experiment"] = 0, ["experiment_result"] = 0, ["suggestion_set"] = 0, ["suggestion"] = 0
                }) + "\n";
            else if (cmd is ["container", "ls", "-aq", "--no-trunc", "--filter", var filter])
                response = filter == "label=" + ownedLabel ? disposable + "\n" : "";
            else if (cmd is ["container", "rm", "--force", "--volumes", var id] && id == disposable && ownedLabel is not null)
            {
                ++Cleanups;
                ownedLabel = null;
            }
            else throw new Exception("Unexpected Docker action");
        }
        else throw new Exception("Docker endpoint was not pinned");
        if (response is not null) await output.WriteAsync(System.Text.Encoding.UTF8.GetBytes(response), ct);
        return 0;
    }
}
