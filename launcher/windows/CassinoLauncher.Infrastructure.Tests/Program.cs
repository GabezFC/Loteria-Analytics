using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Security.AccessControl;
using System.Security.Principal;
using CassinoLauncher.Core;

if (args.Length > 0)
    return await FakeDocker.Run(args);

var scratch = Environment.GetEnvironmentVariable("TMPDIR") ?? Path.GetTempPath();
var dir = Path.GetFullPath(Path.Combine(scratch, "Cassino infraestrutura " + Guid.NewGuid().ToString("N")));
Directory.CreateDirectory(dir);
var path = Path.Combine(dir, ".env-test");
var keys = new[] { "POSTGRES_PASSWORD", "API_PASSWORD", "WORKER_PASSWORD", "INSPECT_PASSWORD" };
var failures = 0;
try
{
    await Test("Primeira criação concorrente, ACL e preservação", async () =>
    {
        await Task.WhenAll(Enumerable.Range(0, 8).Select(_ => Task.Run(() => SecretFile.Ensure(path))));
        var values = Values();
        Check(values.Count == 4 && keys.All(values.ContainsKey));
        Check(values.Values.Distinct().Count() == 4);
        Check(values.Values.All(v => v.Length >= 32 && v.All(char.IsAsciiLetterOrDigit)));
        if (OperatingSystem.IsWindows())
        {
            using var identity = WindowsIdentity.GetCurrent();
            var expected = new[] { identity.User!.Value, new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null).Value };
            var acl = new FileInfo(path).GetAccessControl();
            var rules = acl.GetAccessRules(true, true, typeof(SecurityIdentifier)).Cast<FileSystemAccessRule>().ToArray();
            Check(acl.AreAccessRulesProtected && rules.Length == expected.Distinct().Count());
            foreach (var rule in rules)
                Check(!rule.IsInherited && rule.AccessControlType == AccessControlType.Allow && expected.Contains(rule.IdentityReference.Value));
        }
        else
        {
            Check(File.GetUnixFileMode(path) == (UnixFileMode.UserRead | UnixFileMode.UserWrite));
        }
        File.AppendAllText(path, "# comentário\r\nCASSINO_VERSION=1.2.3\r\n");
        var before = File.ReadAllBytes(path);
        var modified = File.GetLastWriteTimeUtc(path);
        if (OperatingSystem.IsWindows())
        {
            var info = new FileInfo(path);
            var acl = info.GetAccessControl();
            var everyone = new SecurityIdentifier(WellKnownSidType.WorldSid, null);
            acl.AddAccessRule(new FileSystemAccessRule(everyone, FileSystemRights.Read, AccessControlType.Allow));
            info.SetAccessControl(acl);
            SecretFile.Ensure(path);
            foreach (FileSystemAccessRule rule in info.GetAccessControl().GetAccessRules(true, true, typeof(SecurityIdentifier)))
                Check(!rule.IdentityReference.Equals(everyone));
        }
        SecretFile.Ensure(path);
        Check(before.SequenceEqual(File.ReadAllBytes(path)) && modified == File.GetLastWriteTimeUtc(path));
        Check(Directory.GetFiles(dir).SequenceEqual(new[] { path }));
    });
    await Test("Redação literal e bloqueio quando arquivo inválido ou ausente", () =>
    {
        var values = Values();
        var redacted = SecretFile.Redact(path, "prefixo:" + string.Join(",", values.Values) + ":fim");
        Check(redacted.StartsWith("prefixo:") && redacted.EndsWith(":fim"));
        Check(values.Values.All(v => !redacted.Contains(v, StringComparison.Ordinal)));
        var invalid = Path.Combine(dir, "invalid");
        var text = File.ReadAllText(path) + $"\r\n{keys[0]}={values[keys[0]]}\r\n";
        File.WriteAllText(invalid, text);
        try { SecretFile.Ensure(invalid); throw new TestFailure(); }
        catch (IOException ex) { Check(!ex.ToString().Contains(values[keys[0]], StringComparison.Ordinal)); }
        Check(File.ReadAllText(invalid) == text);
        Check(!SecretFile.Redact(invalid, "diagnóstico-sintético").Contains("diagnóstico-sintético"));
        Check(!SecretFile.Redact(invalid + ".ausente", "diagnóstico-sintético").Contains("diagnóstico-sintético"));
        return Task.CompletedTask;
    });
    await Test("Rejeição de reparse point no caminho", async () =>
    {
        var alias = Path.Combine(dir, "alias");
        var target = Path.Combine(dir, "target");
        Directory.CreateDirectory(target);
        if (OperatingSystem.IsWindows())
        {
            // Junctions do not require symlink privileges or Developer Mode.
            var command = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "cmd.exe"))
            {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true,
                RedirectStandardError = true, Arguments = $"/d /c mklink /j \"{alias}\" \"{target}\""
            };
            using var linkProcess = Process.Start(command)!;
            await linkProcess.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(10));
            Check(linkProcess.ExitCode == 0);
        }
        else Directory.CreateSymbolicLink(alias, target);
        try
        {
            var linkedPath = Path.Combine(alias, ".env-test");
            try { SecretFile.Ensure(linkedPath); throw new TestFailure(); }
            catch (IOException) { }
            Check(!File.Exists(Path.Combine(target, ".env-test")));
            Check(!SecretFile.Redact(linkedPath, "diagnóstico-sintético").Contains("diagnóstico-sintético"));
        }
        finally { Directory.Delete(alias); }
    });
    await Test("Argumentos literais, diretório, ambiente e stdin binário", async () =>
    {
        var file = Path.Combine(dir, "entrada bytes.sql");
        await File.WriteAllBytesAsync(file, [0x00, 0x1a, 0x0d, 0x0a, 0xff]);
        var stripped = keys.Concat(new[] { "compose_file", "COMPOSE_ENV_FILES", "COMPOSE_PROJECT_NAME", "CASSINO_VERSION",
            "cassino_custom", "DOCKER_CONTEXT", "DOCKER_HOST", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH" }).ToArray();
        var expected = new[] { "DOCKER_CONFIG" };
        var names = stripped.Concat(expected).ToArray();
        var saved = names.ToDictionary(k => k, Environment.GetEnvironmentVariable);
        try
        {
            foreach (var name in names) Environment.SetEnvironmentVariable(name, "synthetic-value");
            var arg = "literal com espaço & | \"aspas\" \\";
            var result = await Runner().RunAsync(["io", arg, .. names], dir, TimeSpan.FromSeconds(10), default, file);
            var lines = result.Output.Replace("\r\n", "\n").TrimEnd('\n').Split('\n');
            Check(result.Code == 17 && lines.Length == names.Length + 3);
            Check(lines[0] == arg);
            Check(lines[1] == dir);
            Check(lines[2] == "001A0D0AFF");
            Check(lines.Skip(3).Take(stripped.Length).All(s => s == "unset"));
            Check(lines.TakeLast(expected.Length).All(s => s == "synthetic-value"));
        }
        finally { foreach (var (key, value) in saved) Environment.SetEnvironmentVariable(key, value); }
    });
    await Test("Saída limitada com drenagem dos dois pipes", async () =>
    {
        var result = await Runner().RunAsync(["large"], dir, TimeSpan.FromSeconds(15), default);
        Check(result.Code == 0 && result.Output.Length < 1_100_000);
        Check(result.Output.StartsWith("linha completa") && result.Output.EndsWith("[saída do Docker truncada]\n"));
        Check(!result.Output.Contains("stderr-canary") && !result.Output.Contains('x'));
    });
    await Test("Erros de inicialização e stdin não expõem caminhos", async () =>
    {
        var absent = Path.Combine(dir, "sensitive-path-do-not-return.exe");
        await ExpectIo(() => new DockerRunner(absent).RunAsync(["large"], dir, TimeSpan.FromSeconds(5), default), "Docker");
        await ExpectIo(() => Runner().RunAsync(["large"], dir, TimeSpan.FromSeconds(5), default, absent), "entrada");
    });
    await Test("Timeout termina filho e descendente", () => CheckTree(false));
    await Test("Cancelamento termina filho e descendente", () => CheckTree(true));
}
finally { Directory.Delete(dir, recursive: true); }
return failures == 0 ? 0 : 1;

Dictionary<string, string> Values() => File.ReadLines(path).Where(l => !l.StartsWith('#') && l.Contains('='))
    .Select(l => l.Split('=', 2)).Where(parts => keys.Contains(parts[0])).ToDictionary(p => p[0], p => p[1]);

static DockerRunner Runner() => new(Environment.ProcessPath!);
static void Check(bool condition, [CallerArgumentExpression(nameof(condition))] string assertion = "")
{
    if (!condition) throw new TestFailure(assertion);
}

static async Task ExpectIo(Func<Task<CmdResult>> run, string expected)
{
    try { await run(); throw new TestFailure(); }
    catch (IOException ex) { Check(ex.ToString().Contains(expected) && !ex.ToString().Contains("sensitive-path-do-not-return")); }
}

async Task Test(string name, Func<Task> body)
{
    try { await body(); Console.WriteLine($"OK: {name}"); }
    catch (Exception ex)
    {
        // Never print arbitrary exception messages or test fixture secrets.
        var detail = ex is TestFailure failure ? failure.Assertion : ex.GetType().Name;
        Console.Error.WriteLine($"FALHA: {name} ({detail})");
        failures++;
    }
}

async Task CheckTree(bool cancel)
{
    using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(15));
    var pidFile = Path.Combine(dir, cancel ? "cancel.pid" : "timeout.pid");
    var run = Runner().RunAsync(["tree", pidFile], dir, TimeSpan.FromSeconds(cancel ? 20 : 5), cts.Token);
    using var ready = new CancellationTokenSource(TimeSpan.FromSeconds(4));
    int pid = 0;
    while (pid == 0)
    {
        try { int.TryParse(await File.ReadAllTextAsync(pidFile, ready.Token), out pid); }
        catch (IOException) { }
        if (pid == 0) await Task.Delay(30, ready.Token);
    }
    using var child = Process.GetProcessById(pid);
    try
    {
        if (cancel) cts.Cancel();
        try { await run; throw new TestFailure(); }
        catch (OperationCanceledException ex) when (cancel) { Check(ex.CancellationToken == cts.Token); }
        catch (TimeoutException ex) when (!cancel) { Check(ex.Message.Contains("tempo", StringComparison.OrdinalIgnoreCase)); }
        await child.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(5));
    }
    finally { if (!child.HasExited) child.Kill(); }
}

sealed class TestFailure(string assertion = "exceção esperada não ocorreu") : Exception
{
    public string Assertion { get; } = assertion;
}

static class FakeDocker
{
    internal static async Task<int> Run(string[] args)
    {
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        switch (args[0])
        {
            case "io":
                using (var input = new MemoryStream())
                {
                    await Console.OpenStandardInput().CopyToAsync(input);
                    Console.WriteLine(args[1]);
                    Console.WriteLine(Directory.GetCurrentDirectory());
                    Console.WriteLine(Convert.ToHexString(input.ToArray()));
                    foreach (var key in args.Skip(2)) Console.WriteLine(Environment.GetEnvironmentVariable(key) ?? "unset");
                    Console.Error.WriteLine("stderr-canary");
                    return 17;
                }
            case "large":
                var output = new string('x', 8192);
                var error = "stderr-canary" + output;
                Console.WriteLine("linha completa");
                for (var i = 0; i < 256; i++) { Console.Out.Write(output); Console.Error.Write(error); }
                return 0;
            case "tree":
                var start = new ProcessStartInfo(Environment.ProcessPath!) { UseShellExecute = false, CreateNoWindow = true };
                start.ArgumentList.Add("sleep");
                using (var child = Process.Start(start)!)
                    await File.WriteAllTextAsync(args[1], child.Id.ToString());
                break;
            case "sleep":
                break;
            default:
                return 125;
        }
        await Task.Delay(TimeSpan.FromSeconds(60));
        return 0;
    }
}
