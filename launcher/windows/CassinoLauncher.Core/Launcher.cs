using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace CassinoLauncher.Core;

public sealed record ServiceStatus(string Service, string State, string Health);

public sealed class Launcher(string home, string assets, ICommandRunner? runner = null, Action? startDockerDesktop = null)
{
    private readonly string _home = Path.GetFullPath(home);
    private readonly string _assets = Path.GetFullPath(assets);
    private readonly ICommandRunner _docker = runner ?? new DockerRunner();
    private static readonly HttpClient Http = new(new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false }) { Timeout = TimeSpan.FromSeconds(4) };
    private string EnvPath => Path.Combine(_home, ".env");
    private string RuntimePath => Path.Combine(_home, "runtime.env");
    private string ConfigPath => Path.Combine(_home, "config.json");
    private string OwnerPath => Path.Combine(_home, "installation-id");
    public Uri Dashboard => new($"http://127.0.0.1:{Settings.Load(ConfigPath).AppPort}/");

    public async Task StartAsync(IProgress<string> progress, CancellationToken ct)
    {
        using var operation = Lock();
        var cfg = Settings.Load(ConfigPath);
        if (!File.Exists(Path.Combine(_assets, "compose.yaml")) || (cfg.Portainer && !File.Exists(Path.Combine(_assets, "compose.admin.yaml"))))
            throw new InvalidOperationException("Recursos do aplicativo ausentes na pasta app. Repare o pacote do launcher.");
        var migrations = Migrations();
        if (new DriveInfo(Path.GetPathRoot(_home)!).AvailableFreeSpace < 2L * 1024 * 1024 * 1024)
            throw new InvalidOperationException("Libere pelo menos 2 GiB na unidade da configuração. Verifique também o disco do Docker Desktop.");
        Report(progress, "Verificando Docker Desktop e Compose…");
        await ReadyAsync(ct);
        var owner = Owner(create: true)!;
        await CheckOwnership(cfg.Project, owner, ct);
        await CheckOwnership(cfg.AdminProject, owner, ct);
        var before = await CurrentPorts(cfg, ct);
        foreach (var port in ActivePorts(cfg))
            if (!before.Contains(port) && !Free(port)) throw new InvalidOperationException($"Porta local {port} ocupada. Não pare outros contêineres; escolha outra porta no config.json.");
        Settings.SaveNew(ConfigPath, cfg);
        SecretFile.Ensure(EnvPath);
        WriteRuntime(cfg, owner);
        await Must(Main(cfg, "config", "--quiet"), "Configuração Compose principal inválida.", ct);
        if (cfg.Portainer) await Must(Admin(cfg, "config", "--quiet"), "Configuração Compose do Portainer inválida.", ct);
        Report(progress, "Preparando imagens e iniciando PostgreSQL…");
        await Must(Main(cfg, "up", "-d", "--wait", "--wait-timeout", "120", "--no-build", "postgres"), "PostgreSQL indisponível ou imagem ausente.", ct, 240);
        Report(progress, "Verificando migrações do banco…");
        await Migrate(cfg, migrations, ct);
        var services = new List<string> { "up", "-d", "--wait", "--wait-timeout", "180", "--no-build", "postgres", "backend", "frontend", "coletor", "analisador" };
        if (cfg.CloudBeaver) services.Add("cloudbeaver");
        Report(progress, "Iniciando aplicação e workers. A coleta histórica pode continuar em segundo plano.");
        await Must(Main(cfg, services.ToArray()), "Falha ao iniciar a aplicação. Confira Status e Logs, ou prepare as imagens versionadas do pacote.", ct, 420);
        if (cfg.Portainer)
        {
            Report(progress, "Iniciando Portainer em stack separada…");
            await Must(Admin(cfg, "up", "-d", "--wait", "--wait-timeout", "90", "--no-build", "portainer"), "Falha ao iniciar o Portainer local.", ct, 240);
        }
        if (!await HealthAsync(ct)) throw new InvalidOperationException("Os contêineres iniciaram, mas o dashboard não respondeu ao teste de saúde.");
        Report(progress, "Dashboard pronto.");
    }

    public async Task StopAsync(IProgress<string> progress, CancellationToken ct)
    {
        using var operation = Lock();
        var cfg = Settings.Load(ConfigPath);
        if (!Prepared()) { Report(progress, "Nenhuma instância configurada."); return; }
        await VerifyBoth(cfg, ct);
        Report(progress, "Parando os serviços da aplicação sem remover dados…");
        await Must(Main(cfg, "stop", "--timeout", "20"), "Falha ao parar a aplicação.", ct, 120);
        // Portainer tem ciclo de vida separado, inclusive no botão Reiniciar.
        Report(progress, "Aplicação parada; volumes e Portainer preservados.");
    }

    public async Task<IReadOnlyList<ServiceStatus>> StatusAsync(CancellationToken ct)
    {
        var cfg = Settings.Load(ConfigPath);
        var expected = new List<string> { "postgres", "backend", "frontend", "coletor", "analisador" };
        if (cfg.CloudBeaver) expected.Add("cloudbeaver");
        if (cfg.Portainer) expected.Add("portainer");
        if (!Prepared()) return expected.Select(s => new ServiceStatus(s, "não iniciado", "")).ToList();
        await VerifyBoth(cfg, ct);
        var rows = await ReadPs(Main(cfg, "ps", "-a", "--format", "json"), ct);
        if (cfg.Portainer) rows.AddRange(await ReadPs(Admin(cfg, "ps", "-a", "--format", "json"), ct));
        return expected.Select(s => rows.FirstOrDefault(r => r.Service == s) ?? new ServiceStatus(s, "ausente", "")).ToList();
    }

    public async Task<string> LogsAsync(CancellationToken ct)
    {
        var cfg = Settings.Load(ConfigPath);
        if (!Prepared()) return "Nenhuma instância iniciada.";
        await VerifyBoth(cfg, ct);
        // Consoles podem registrar tokens de bootstrap que não pertencem ao .env.
        var text = await Must(Main(cfg, "logs", "--no-color", "--tail", "30", "postgres", "backend", "frontend", "coletor", "analisador"), "Falha ao ler logs da aplicação.", ct);
        return SecretFile.Redact(EnvPath, text);
    }

    public async Task<bool> HealthAsync(CancellationToken ct)
    {
        if (!Prepared()) return false;
        var cfg = Settings.Load(ConfigPath);
        await CheckLocalContext(ct);
        await CheckOwnership(cfg.Project, Owner(false)!, ct);
        var states = await ReadPs(Main(cfg, "ps", "--format", "json", "frontend"), ct);
        if (!states.Any(s => s.Service == "frontend" && s.State == "running" && s.Health == "healthy")) return false;
        try { using var response = await Http.GetAsync(new Uri(Dashboard, "api/health"), ct); return response.StatusCode == HttpStatusCode.OK; }
        catch (HttpRequestException) { return false; }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested) { return false; }
    }

    public async Task<RecoveryResult> BackupAsync(string destination, CancellationToken ct)
    {
        using var operation = Lock();
        if (!Prepared()) throw new InvalidOperationException("Inicie a instalação antes de criar um backup.");
        var cfg = Settings.Load(ConfigPath);
        await VerifyBoth(cfg, ct);
        var id = (await Must(Main(cfg, "ps", "--quiet", "postgres"), "PostgreSQL da instalação indisponível.", ct)).Trim();
        if (!Regex.IsMatch(id, @"\A[a-f0-9]{64}\z")) throw new InvalidOperationException("Nenhum PostgreSQL ativo identificado para esta instalação.");
        return await new DockerRecovery().BackupAsync(id, destination, ct: ct);
    }

    public async Task<RecoveryResult> VerifyBackupAsync(string bundle, CancellationToken ct)
    {
        using var operation = Lock();
        return await new DockerRecovery().VerifyAsync(bundle, ct: ct);
    }

    private async Task ReadyAsync(CancellationToken ct)
    {
        var compose = await Must(["compose", "version", "--short"], "Docker CLI ou plugin Compose ausente. Instale ou atualize o Docker Desktop oficial.", ct);
        var match = Regex.Match(compose.Trim(), @"\Av?(\d+)\.(\d+)");
        if (!match.Success || !int.TryParse(match.Groups[1].Value, out var major) || !int.TryParse(match.Groups[2].Value, out var minor) || major < 2 || (major == 2 && minor < 24))
            throw new InvalidOperationException("É necessário Docker Compose v2.24 ou mais recente.");
        await CheckLocalContext(ct);
        var deadline = Stopwatch.StartNew();
        var launched = false;
        while (deadline.Elapsed < TimeSpan.FromMinutes(3))
        {
            CmdResult? info = null;
            try { info = await _docker.RunAsync(["info", "--format", "{{.OSType}}"], _assets, TimeSpan.FromSeconds(8), ct); }
            catch (TimeoutException) { }
            if (info?.Code == 0)
            {
                if (info.Output.Trim() != "linux") throw new InvalidOperationException("Selecione contêineres Linux no Docker Desktop.");
                return;
            }
            if (!launched)
            {
                (startDockerDesktop ?? OpenDockerDesktop)();
                launched = true;
            }
            await Task.Delay(TimeSpan.FromSeconds(Math.Min(8, 2 + deadline.Elapsed.TotalSeconds / 12)), ct);
        }
        throw new TimeoutException("O Docker Desktop não ficou pronto. Verifique WSL2/virtualização e avisos de inicialização no Docker Desktop e tente novamente.");
    }

    private static void OpenDockerDesktop()
    {
        if (!OperatingSystem.IsWindows()) throw new InvalidOperationException("Engine do Docker indisponível.");
        var desktop = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Docker", "Docker", "Docker Desktop.exe");
        if (!File.Exists(desktop)) throw new InvalidOperationException("Docker Desktop não encontrado no local padrão. Instale-o ou abra sua instalação existente manualmente.");
        using var own = Process.Start(new ProcessStartInfo(desktop) { UseShellExecute = false });
    }

    private async Task CheckLocalContext(CancellationToken ct)
    {
        var context = (await Must(["context", "show"], "Não foi possível verificar o contexto Docker.", ct)).Trim();
        if (context is not ("desktop-linux" or "default")) throw new InvalidOperationException("Selecione o contexto local do Docker Desktop (desktop-linux ou default).");
        var endpoint = (await Must(["context", "inspect", context, "--format", "{{.Endpoints.docker.Host}}"], "Não foi possível verificar o endpoint Docker.", ct)).Trim();
        if (endpoint is not ("npipe:////./pipe/dockerDesktopLinuxEngine" or "npipe:////./pipe/docker_engine"))
            throw new InvalidOperationException("O contexto Docker não aponta para o engine local do Windows.");
    }

    private async Task CheckOwnership(string project, string owner, CancellationToken ct)
    {
        var label = $"label=com.docker.compose.project={project}";
        // Containers also carry a working directory. Volumes/networks survive the containers.
        var templates = new[] { (new[] { "ps", "-a" }, "{{.ID}}", "container"), (new[] { "volume", "ls" }, "{{.Name}}", "volume"), (new[] { "network", "ls" }, "{{.Name}}", "network") };
        foreach (var (list, identifier, kind) in templates)
        {
            var output = await Must([.. list, "--filter", label, "--format", identifier], "Não foi possível verificar a identidade da stack Docker.", ct);
            var ids = output.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries).ToHashSet(StringComparer.Ordinal);
            if (kind != "container")
            {
                var names = kind == "network" ? new[] { project + "_default" } : new[] { project + "_postgres_data", project + "_cloudbeaver_workspace", project + "_portainer_data" };
                var all = await Must([.. list, "--format", identifier], "Não foi possível verificar nomes dos recursos Docker.", ct);
                ids.UnionWith(all.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries).Intersect(names, StringComparer.Ordinal));
            }
            foreach (var id in ids)
            {
                var opts = kind == "container" ? "{{ index .Config.Labels \"io.cassino.launcher.owner\" }}" : "{{ index .Labels \"io.cassino.launcher.owner\" }}";
                if ((await Must([kind, "inspect", "--format", opts, id], "Não foi possível verificar um recurso Docker.", ct)).Trim() != owner)
                    throw new InvalidOperationException($"Projeto Docker {project} já possui dados de outra instalação. Nenhum recurso será adotado.");
                if (kind == "container")
                {
                    var path = (await Must([kind, "inspect", "--format", "{{ index .Config.Labels \"com.docker.compose.project.working_dir\" }}", id], "Não foi possível verificar o diretório da stack.", ct)).Trim();
                    if (!Path.IsPathFullyQualified(path) || !Path.TrimEndingDirectorySeparator(Path.GetFullPath(path)).Equals(Path.TrimEndingDirectorySeparator(_assets), StringComparison.OrdinalIgnoreCase))
                        throw new InvalidOperationException($"Contêiner de {project} pertence a outro diretório. Operação interrompida.");
                }
            }
        }
    }

    private async Task VerifyBoth(Settings cfg, CancellationToken ct)
    {
        await CheckLocalContext(ct);
        var owner = Owner(false)!;
        await CheckOwnership(cfg.Project, owner, ct);
        await CheckOwnership(cfg.AdminProject, owner, ct);
    }

    private async Task<HashSet<int>> CurrentPorts(Settings cfg, CancellationToken ct)
    {
        // Before env generation, directly inspect only owned running project containers.
        var owned = new HashSet<int>();
        foreach (var project in new[] { cfg.Project, cfg.AdminProject })
        {
            var ids = await Must(["ps", "--filter", $"label=com.docker.compose.project={project}", "--format", "{{.ID}}"], "Não foi possível verificar portas Docker.", ct);
            foreach (var id in ids.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries))
            {
                var ports = await Must(["inspect", "--format", "{{json .NetworkSettings.Ports}}", id], "Não foi possível verificar portas Docker.", ct);
                using var doc = JsonDocument.Parse(ports);
                if (doc.RootElement.ValueKind != JsonValueKind.Object) continue;
                foreach (var binding in doc.RootElement.EnumerateObject().Where(kv => kv.Value.ValueKind == JsonValueKind.Array).SelectMany(kv => kv.Value.EnumerateArray()))
                    if (binding.GetProperty("HostIp").GetString() == "127.0.0.1" && int.TryParse(binding.GetProperty("HostPort").GetString(), out var port)) owned.Add(port);
            }
        }
        return owned;
    }

    private static IEnumerable<int> ActivePorts(Settings c)
    {
        yield return c.AppPort;
        if (c.CloudBeaver) yield return c.CloudBeaverPort;
        if (c.Portainer) yield return c.PortainerPort;
    }

    private static bool Free(int port)
    {
        var socket = new TcpListener(IPAddress.Loopback, port) { ExclusiveAddressUse = true };
        try { socket.Start(); return true; }
        catch (SocketException) { return false; }
        finally { socket.Stop(); }
    }

    private string[] Migrations()
    {
        var dir = Path.Combine(_assets, "infra", "postgres");
        if (!File.Exists(Path.Combine(dir, "001-base.sh"))) throw new InvalidOperationException("Script base do PostgreSQL ausente.");
        return Enumerable.Range(2, 5).Select(n => Directory.GetFiles(dir, $"{n:000}-*.sql").SingleOrDefault() ?? throw new InvalidOperationException($"Migração {n:000} ausente.")).ToArray();
    }

    private async Task Migrate(Settings cfg, string[] files, CancellationToken ct)
    {
        var psql = new[] { "exec", "-T", "postgres", "psql", "-X", "-U", "postgres", "-d", "cassino", "-v", "ON_ERROR_STOP=1" };
        async Task<string> Query(string sql) => (await Must(Main(cfg, [.. psql, "-Atqc", sql]), "Falha ao conferir o schema do PostgreSQL.", ct)).Trim();
        var log = await Query("SELECT to_regclass('public.schema_migration') IS NOT NULL;");
        var installed = new HashSet<string>(StringComparer.Ordinal);
        if (log == "t")
            installed.UnionWith((await Query("SELECT name FROM public.schema_migration ORDER BY name;")).Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries));
        var expected = files.Select(f => Path.GetFileNameWithoutExtension(f)!).ToArray();
        if (installed.Except(expected).Any() || !installed.SetEquals(expected.Take(installed.Count)))
            throw new InvalidOperationException("Histórico de migrações incompatível. Preserve o banco e revise antes de prosseguir.");
        var firstExists = await Query("SELECT to_regclass('public.lottery_draw') IS NOT NULL AND to_regclass('public.ingest_run') IS NOT NULL;") == "t";
        if (installed.Count > 0 && !firstExists) throw new InvalidOperationException("Schema de ingestão incompleto. Operação interrompida.");
        for (var i = installed.Count; i < files.Length; i++)
        {
            // 002 is a transaction but its marker is written by 003. A crash between them must not replay 002.
            if (i == 0 && firstExists) continue;
            await Must(Main(cfg, [.. psql, "-f", "-"]), $"Falha na migração {expected[i]}. Serviços escritores não foram iniciados.", ct, 90, files[i]);
        }
        var final = (await Query("SELECT name FROM public.schema_migration ORDER BY name;")).Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (!final.SequenceEqual(expected)) throw new InvalidOperationException("Histórico de migrações incompleto após execução.");
    }

    private async Task<List<ServiceStatus>> ReadPs(string[] args, CancellationToken ct)
    {
        var response = (await Must(args, "Falha ao consultar estado dos contêineres.", ct)).Trim();
        var rows = new List<ServiceStatus>();
        if (response.StartsWith('['))
        {
            using var doc = JsonDocument.Parse(response);
            rows.AddRange(doc.RootElement.EnumerateArray().Select(ToStatus));
        }
        else foreach (var line in response.Split('\n', StringSplitOptions.RemoveEmptyEntries))
        {
            using var doc = JsonDocument.Parse(line);
            rows.Add(ToStatus(doc.RootElement));
        }
        return rows;
    }

    private static ServiceStatus ToStatus(JsonElement row) => new(Field(row, "Service"), Field(row, "State"), Field(row, "Health"));
    private static string Field(JsonElement row, string field) => row.TryGetProperty(field, out var val) && val.ValueKind == JsonValueKind.String ? val.GetString()! : "";

    private string[] Main(Settings c, params string[] args) => Compose(c.Project, "compose.yaml", ["-f", Path.Combine(_assets, "lan", "compose.local.yaml"), .. args]);
    private string[] Admin(Settings c, params string[] args) => Compose(c.AdminProject, "compose.admin.yaml", args);
    private string[] Compose(string id, string file, string[] args) =>
        ["compose", "--project-directory", _assets, "--env-file", EnvPath, "--env-file", RuntimePath, "-p", id, "-f", Path.Combine(_assets, file), .. args];

    private async Task<string> Must(string[] args, string error, CancellationToken ct, int seconds = 25, string? input = null)
    {
        var result = await _docker.RunAsync(args, _assets, TimeSpan.FromSeconds(seconds), ct, input);
        if (result.Code != 0) throw new InvalidOperationException($"{error} (Docker: código {result.Code})");
        return result.Output;
    }

    private FileStream Lock()
    {
        Directory.CreateDirectory(_home);
        try { return File.Open(Path.Combine(_home, "operation.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None); }
        catch (IOException) { throw new InvalidOperationException("Outra operação do launcher já está em execução."); }
    }

    private bool Prepared() => File.Exists(ConfigPath) && File.Exists(OwnerPath) && File.Exists(RuntimePath) && File.Exists(EnvPath);

    private string? Owner(bool create)
    {
        if (!File.Exists(OwnerPath))
        {
            if (!create) return null;
            File.WriteAllText(OwnerPath, Convert.ToHexString(RandomNumberGenerator.GetBytes(16)).ToLowerInvariant());
        }
        var owner = File.ReadAllText(OwnerPath).Trim();
        if (!Regex.IsMatch(owner, @"\A[a-f0-9]{32}\z")) throw new InvalidOperationException("Identidade local da instalação inválida.");
        return owner;
    }

    private void WriteRuntime(Settings c, string owner) => File.WriteAllText(RuntimePath,
        FormattableString.Invariant($"CASSINO_LAUNCHER_OWNER={owner}\nCASSINO_APP_PORT={c.AppPort}\nCASSINO_CLOUDBEAVER_PORT={c.CloudBeaverPort}\nCASSINO_PORTAINER_PORT={c.PortainerPort}\n"));

    private void Report(IProgress<string> progress, string text)
    {
        progress.Report(text);
        var dir = Path.Combine(_home, "logs");
        Directory.CreateDirectory(dir);
        var path = Path.Combine(dir, "launcher.log");
        if (File.Exists(path) && new FileInfo(path).Length > 256 * 1024) File.Move(path, path + ".previous", true);
        File.AppendAllText(path, $"{DateTimeOffset.Now:O} {text}{Environment.NewLine}");
    }
}
