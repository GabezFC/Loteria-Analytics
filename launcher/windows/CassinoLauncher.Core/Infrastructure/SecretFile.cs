using System.Runtime.Versioning;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;

namespace CassinoLauncher.Core;

public static class SecretFile
{
    private const int MaxFileBytes = 64 * 1024;
    private const UnixFileMode PrivateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite;
    private const string HiddenOutput = "[saída omitida: não foi possível proteger os segredos do Cassino]";
    private static readonly string[] PasswordKeys = ["POSTGRES_PASSWORD", "API_PASSWORD", "WORKER_PASSWORD", "INSPECT_PASSWORD"];
    private static readonly UTF8Encoding Utf8 = new(false, true);
    // Deliberately accept a conservative subset of Compose env syntax: no interpolation or multiline values.
    private static readonly Regex EnvLine = new("^[ \\t]*([A-Za-z_][A-Za-z0-9_]*)[ \\t]*=[ \\t]*(?:([A-Za-z0-9_.-]*)|'([A-Za-z0-9_.-]*)'|\"([A-Za-z0-9_.-]*)\")(?:[ \\t]+#.*)?[ \\t]*$", RegexOptions.NonBacktracking);

    internal static bool IsPasswordKey(string key) => PasswordKeys.Contains(key, StringComparer.OrdinalIgnoreCase);

    public static void Ensure(string path)
    {
        try
        {
            var fullPath = Normalize(path);
            if (CheckPath(fullPath))
            {
                ValidateAndProtect(fullPath);
                return;
            }

            var directory = Path.GetDirectoryName(fullPath)!;
            Directory.CreateDirectory(directory);
            if (CheckPath(fullPath))
            {
                ValidateAndProtect(fullPath);
                return;
            }

            var temp = Path.Combine(directory, ".cassino-env-" + Guid.NewGuid().ToString("N") + ".tmp");
            var created = false;
            try
            {
                using (var file = CreatePrivate(temp))
                {
                    created = true;
                    var content = new StringBuilder("# Configuração local do Cassino. Não compartilhar.\n");
                    var generated = new HashSet<string>(StringComparer.Ordinal);
                    foreach (var key in PasswordKeys)
                    {
                        string value;
                        do { value = Convert.ToHexString(RandomNumberGenerator.GetBytes(24)); }
                        while (!generated.Add(value));
                        content.Append(key).Append('=').Append(value).Append('\n');
                    }
                    file.Write(Utf8.GetBytes(content.ToString()));
                    file.Flush(flushToDisk: true);
                }

                // Same directory/volume, no overwrite: a concurrent first run may win the race.
                try { File.Move(temp, fullPath, overwrite: false); }
                catch (IOException) when (CheckPath(fullPath)) { ValidateAndProtect(fullPath); }
            }
            finally { if (created) File.Delete(temp); }
        }
        catch (InvalidEnvException)
        {
            throw new IOException("O arquivo .env do Cassino é inválido ou incompleto. Ele não foi substituído.");
        }
        catch (Exception ex) when (IsFileError(ex))
        {
            throw new IOException("Não foi possível acessar ou proteger o arquivo .env do Cassino. Verifique as permissões e se o caminho contém links.");
        }
    }

    // Call on raw stdout before showing or logging it. Never fall back to unredacted text.
    public static string Redact(string path, string text)
    {
        if (string.IsNullOrEmpty(text))
            return string.Empty;
        try
        {
            var fullPath = Normalize(path);
            if (!CheckPath(fullPath))
                return HiddenOutput;
            var values = ReadPasswords(fullPath);
            // Prefer the longest match at a given position and never re-match replacement text.
            var pattern = string.Join('|', values.OrderByDescending(v => v.Length).Select(Regex.Escape));
            return Regex.Replace(text, pattern, "[segredo oculto]", RegexOptions.CultureInvariant,
                TimeSpan.FromSeconds(1));
        }
        catch (Exception ex) when (IsFileError(ex) || ex is InvalidEnvException or RegexMatchTimeoutException)
        {
            return HiddenOutput;
        }
    }

    private static string Normalize(string path)
    {
        var full = Path.GetFullPath(path);
        var root = Path.GetPathRoot(full)!;
        if (full.Length == root.Length || Path.GetFileName(full).Length == 0 ||
            (OperatingSystem.IsWindows() && (full.StartsWith(@"\\?\", StringComparison.Ordinal) ||
                full.StartsWith(@"\\.\", StringComparison.Ordinal) || full.AsSpan(root.Length).Contains(':'))))
            throw new InvalidEnvException();
        return full;
    }

    // Inspect the ancestors first, without relying on File.Exists (which can mask reparse points).
    private static bool CheckPath(string path)
    {
        var parent = Path.GetDirectoryName(path);
        if (parent is not null && !CheckPath(parent))
            return false;
        try
        {
            var attributes = File.GetAttributes(path);
            if ((attributes & (FileAttributes.ReparsePoint | FileAttributes.Device)) != 0)
                throw new InvalidEnvException();
            return true;
        }
        catch (FileNotFoundException) { return false; }
        catch (DirectoryNotFoundException) { return false; }
    }

    private static string[] ReadPasswords(string path)
    {
        using var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        var bytes = new byte[MaxFileBytes + 1];
        var size = file.ReadAtLeast(bytes, bytes.Length, throwOnEndOfStream: false);
        if (size > MaxFileBytes)
            throw new InvalidEnvException();
        var text = Utf8.GetString(bytes, 0, size);
        if (text.StartsWith('\uFEFF'))
            text = text[1..];
        using var lines = new StringReader(text);
        var passwords = new Dictionary<string, string>(StringComparer.Ordinal);
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        while (lines.ReadLine() is string line)
        {
            if (line.Contains('\0'))
                throw new InvalidEnvException();
            var trimmed = line.Trim(' ', '\t');
            if (trimmed.Length == 0 || trimmed.StartsWith('#'))
                continue;
            var match = EnvLine.Match(line);
            if (!match.Success)
                throw new InvalidEnvException();
            var key = match.Groups[1].Value;
            if (!seen.Add(key))
                throw new InvalidEnvException();
            if (!IsPasswordKey(key))
                continue;
            var value = match.Groups[2].Value + match.Groups[3].Value + match.Groups[4].Value;
            if (!PasswordKeys.Contains(key, StringComparer.Ordinal) || value.Length is < 16 or > 256)
                throw new InvalidEnvException();
            passwords.Add(key, value);
        }
        if (passwords.Count != PasswordKeys.Length || passwords.Values.Distinct(StringComparer.Ordinal).Count() != PasswordKeys.Length)
            throw new InvalidEnvException();
        return passwords.Values.ToArray();
    }

    private static void ValidateAndProtect(string path)
    {
        _ = ReadPasswords(path);
        if (!CheckPath(path))
            throw new InvalidEnvException();
        if (OperatingSystem.IsWindows())
            new FileInfo(path).SetAccessControl(PrivateAcl());
        else
            File.SetUnixFileMode(path, PrivateMode);
    }

    private static FileStream CreatePrivate(string path)
    {
        if (OperatingSystem.IsWindows())
            return new FileInfo(path).Create(FileMode.CreateNew, FileSystemRights.Write, FileShare.None,
                4096, FileOptions.None, PrivateAcl());
        return new FileStream(path, new FileStreamOptions
        {
            Mode = FileMode.CreateNew, Access = FileAccess.Write, UnixCreateMode = PrivateMode
        });
    }

    [SupportedOSPlatform("windows")]
    private static FileSecurity PrivateAcl()
    {
        using var identity = WindowsIdentity.GetCurrent();
        var user = identity.User ?? throw new InvalidEnvException();
        var system = new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null);
        var acl = new FileSecurity();
        acl.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
        foreach (var sid in new[] { user, system }.Distinct())
            acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl, AccessControlType.Allow));
        return acl;
    }

    private static bool IsFileError(Exception ex) => ex is IOException or UnauthorizedAccessException or
        ArgumentException or NotSupportedException or System.Security.SecurityException;

    private sealed class InvalidEnvException : Exception;
}
