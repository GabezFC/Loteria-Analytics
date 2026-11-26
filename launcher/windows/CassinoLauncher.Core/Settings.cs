using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace CassinoLauncher.Core;

public sealed record Settings
{
    public string Project { get; init; } = "cassino-launcher";
    public string AdminProject { get; init; } = "cassino-launcher-admin";
    public int AppPort { get; init; } = 3000;
    public int CloudBeaverPort { get; init; } = 8978;
    public int PortainerPort { get; init; } = 9443;
    public bool CloudBeaver { get; init; } = true;
    public bool Portainer { get; init; } = true;

    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        AllowDuplicateProperties = false,
        WriteIndented = true
    };

    public static Settings Parse(string json)
    {
        Settings cfg;
        try { cfg = JsonSerializer.Deserialize<Settings>(json, Json) ?? throw new JsonException(); }
        catch (JsonException) { throw new InvalidOperationException("config.json inválido. O arquivo não foi alterado."); }
        var ports = new[] { cfg.AppPort, cfg.CloudBeaverPort, cfg.PortainerPort };
        if (ports.Any(p => p is < 1024 or > 65535) || ports.Distinct().Count() != ports.Length ||
            !ValidName(cfg.Project) || !ValidName(cfg.AdminProject) || cfg.AdminProject != cfg.Project + "-admin")
            throw new InvalidOperationException("Use portas distintas de 1024 a 65535 e nomes próprios: cassino-<instância> e cassino-<instância>-admin.");
        return cfg;
    }

    private static bool ValidName(string? name) => name is not null && name != "cassino-admin" &&
        Regex.IsMatch(name, @"\Acassino-[a-z0-9][a-z0-9-]{0,43}\z", RegexOptions.CultureInvariant);

    internal static Settings Load(string path) => File.Exists(path) ? Parse(File.ReadAllText(path)) : new Settings();

    internal static void SaveNew(string path, Settings settings)
    {
        if (File.Exists(path)) return;
        var temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { File.WriteAllText(temp, JsonSerializer.Serialize(settings, Json)); File.Move(temp, path, overwrite: false); }
        finally { File.Delete(temp); }
    }
}
