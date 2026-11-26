using CassinoLauncher.Core;

var settings = Settings.Parse("{}");
Assert(settings.Project != "cassino" && settings.AdminProject != "cassino-admin", "não adota produção");
Assert(settings.AppPort == 3000 && settings.AdminProject != settings.Project, "padrões");
Assert(Settings.Parse("""{"project":"cassino-test1","adminProject":"cassino-test1-admin","appPort":23000}""").AppPort == 23000, "porta isolada");
Reject("""{"appPort":8978}""");
Reject("""{"project":"cassino"}""");
Reject("""{"project":"bad name"}""");
Reject("""{"appPort":22}""");
Reject("""{"extra":0}""");
Reject("""{"appPort":3001,"appPort":3002}""");
Console.WriteLine("8 testes de configuração aprovados");

// Exercita o aceite fail-closed sem consultar o Docker da máquina.
var root = Path.Combine(Path.GetTempPath(), "cassino-core-test-" + Guid.NewGuid().ToString("N"));
try
{
    var assets = Path.Combine(root, "app");
    var sql = Path.Combine(assets, "infra", "postgres");
    Directory.CreateDirectory(sql);
    foreach (var file in new[] { "compose.yaml", "compose.admin.yaml", "infra/postgres/001-base.sh", "infra/postgres/002-a.sql", "infra/postgres/003-b.sql", "infra/postgres/004-c.sql", "infra/postgres/005-d.sql", "infra/postgres/006-e.sql" })
        File.WriteAllText(Path.Combine(assets, file), "fixture");
    var home = Path.Combine(root, "home");
    var remote = new TestDocker(remote: true);
    await RejectStart(new Launcher(home, assets, remote), "contexto Docker não aponta");
    Assert(!remote.Calls.Any(a => a[0] is "info" or "ps"), "remote recusado antes de ver recursos");
    var collision = new TestDocker(remote: false);
    await RejectStart(new Launcher(home, assets, collision), "outra instalação");
    Assert(!collision.Calls.Any(a => a.Contains("up")), "propriedade recusada antes de iniciar");
    Assert(!File.Exists(Path.Combine(home, ".env")), "sem credenciais antes da validação de propriedade");
    Console.WriteLine("5 verificações de isolamento Docker aprovadas");
    var dockerClosed = new TestDocker(remote: false, initiallyClosed: true);
    var launches = 0;
    await RejectStart(new Launcher(home, assets, dockerClosed, () => { launches++; }), "outra instalação");
    Assert(launches == 1 && dockerClosed.Calls.Count(a => a[0] == "info") == 2, "daemon parado aciona Desktop uma vez e reconsulta antes de tocar a stack");
    Console.WriteLine("Fluxo de Docker fechado simulado aprovado");
}
finally { if (Directory.Exists(root)) Directory.Delete(root, recursive: true); }

static void Assert(bool match, string name) { if (!match) throw new Exception(name); }
static void Reject(string json) { try { Settings.Parse(json); } catch (InvalidOperationException) { return; } throw new Exception("Aceitou configuração inválida"); }
static async Task RejectStart(Launcher launcher, string message)
{
    try { await launcher.StartAsync(new QuietProgress(), CancellationToken.None); }
    catch (InvalidOperationException error) when (error.Message.Contains(message, StringComparison.OrdinalIgnoreCase)) { return; }
    throw new Exception("Início não foi recusado: " + message);
}

sealed class TestDocker(bool remote, bool initiallyClosed = false) : ICommandRunner
{
    public List<IReadOnlyList<string>> Calls { get; } = [];
    public Task<CmdResult> RunAsync(IReadOnlyList<string> args, string directory, TimeSpan timeout, CancellationToken ct, string? inputFile = null)
    {
        Calls.Add(args);
        if (initiallyClosed && args[0] == "info" && Calls.Count(a => a[0] == "info") == 1)
            return Task.FromResult(new CmdResult(1, ""));
        string text = (args[0], args.Count > 1 ? args[1] : "") switch
        {
            ("compose", "version") => "2.40.0",
            ("context", "show") => "default",
            ("context", "inspect") => remote ? "tcp://test.invalid:2376" : "npipe:////./pipe/docker_engine",
            ("info", _) => "linux",
            ("ps", "-a") => "fake-id",
            ("container", "inspect") => "other-install",
            _ => throw new Exception("Chamada Docker inesperada")
        };
        return Task.FromResult(new CmdResult(0, text));
    }
}

sealed class QuietProgress : IProgress<string> { public void Report(string value) { } }
