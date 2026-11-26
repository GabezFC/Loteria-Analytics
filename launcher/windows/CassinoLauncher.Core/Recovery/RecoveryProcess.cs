using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text;

[assembly: InternalsVisibleTo("CassinoLauncher.Recovery.Tests")]

namespace CassinoLauncher.Core;

internal interface IRecoveryProcess
{
    Task<int> RunAsync(string[] args, TimeSpan timeout, CancellationToken ct, Stream output, Stream? input = null);
}

// Archives never pass through a StreamReader, console, or logger.
internal sealed class RecoveryProcess : IRecoveryProcess
{
    private string? executable;

    public async Task<int> RunAsync(string[] args, TimeSpan timeout, CancellationToken ct, Stream output, Stream? input = null)
    {
        ct.ThrowIfCancellationRequested();
        var start = new ProcessStartInfo
        {
            FileName = executable ??= FindDocker(),
            WorkingDirectory = Path.GetDirectoryName(Environment.ProcessPath)!,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
            StandardInputEncoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false)
        };
        foreach (var arg in args) start.ArgumentList.Add(arg);
        foreach (var key in start.Environment.Keys.ToArray())
        {
            var upper = key.ToUpperInvariant();
            if (upper.StartsWith("COMPOSE_") || upper.StartsWith("CASSINO_") || upper.StartsWith("DOCKER_") ||
                upper.StartsWith("PG") || SecretFile.IsPasswordKey(key))
                start.Environment.Remove(key);
        }

        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(timeout);
        using var process = new Process { StartInfo = start };
        try
        {
            ct.ThrowIfCancellationRequested();
            if (!process.Start()) throw new IOException("Não foi possível iniciar a CLI do Docker.");
        }
        catch (Win32Exception)
        {
            throw new IOException("Não foi possível iniciar a CLI do Docker. Confira a instalação e o PATH.");
        }

        var token = deadline.Token;
        var tasks = new[]
        {
            process.StandardOutput.BaseStream.CopyToAsync(output, token),
            process.StandardError.BaseStream.CopyToAsync(Stream.Null, token),
            SendAsync(process.StandardInput.BaseStream, input, token),
            process.WaitForExitAsync(token)
        };
        try
        {
            // A failed copy (e.g. disk full) must stop the producer, not wait for its blocked pipe.
            var pending = tasks.ToList();
            while (pending.Count != 0)
            {
                var task = await Task.WhenAny(pending).WaitAsync(token).ConfigureAwait(false);
                pending.Remove(task);
                await task.ConfigureAwait(false);
            }
            token.ThrowIfCancellationRequested();
            return process.ExitCode;
        }
        catch (Exception ex) when (ex is IOException or OperationCanceledException || token.IsCancellationRequested)
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
            catch (Exception kill) when (kill is Win32Exception or InvalidOperationException or NotSupportedException) { }
            try { await Task.WhenAll(tasks).WaitAsync(TimeSpan.FromSeconds(3)).ConfigureAwait(false); }
            catch (Exception) { }
            ct.ThrowIfCancellationRequested();
            if (token.IsCancellationRequested) throw new TimeoutException("Tempo limite excedido na operação Docker de recuperação.");
            throw new IOException("Falha no fluxo de dados da operação Docker de recuperação.");
        }
    }

    private static async Task SendAsync(Stream pipe, Stream? input, CancellationToken ct)
    {
        using (pipe)
        {
            if (input is not null) await input.CopyToAsync(pipe, ct).ConfigureAwait(false);
        }
    }

    private static string FindDocker()
    {
        var name = OperatingSystem.IsWindows() ? "docker.exe" : "docker";
        foreach (var entry in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
        {
            var path = entry.Trim('"');
            if (Path.IsPathFullyQualified(path) && File.Exists(Path.Combine(path, name))) return Path.Combine(path, name);
        }
        throw new IOException("CLI do Docker não encontrada no PATH.");
    }
}
