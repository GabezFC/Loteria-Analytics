using System.ComponentModel;
using System.Diagnostics;
using System.Text;

namespace CassinoLauncher.Core;

public sealed record CmdResult(int Code, string Output);

public interface ICommandRunner
{
    Task<CmdResult> RunAsync(IReadOnlyList<string> args, string workingDirectory, TimeSpan timeout,
        CancellationToken ct, string? inputFile = null);
}

public sealed class DockerRunner : ICommandRunner
{
    private const int MaxOutputChars = 1024 * 1024;
    private readonly string? executable;

    public DockerRunner() { }

    // Explicit test seam: never consult this path in the default constructor.
    public DockerRunner(string executable)
    {
        if (!Path.IsPathFullyQualified(executable) ||
            (OperatingSystem.IsWindows() && !Path.GetExtension(executable).Equals(".exe", StringComparison.OrdinalIgnoreCase)))
            throw new ArgumentException("Informe o caminho absoluto de um executável.", nameof(executable));
        this.executable = executable;
    }

    public async Task<CmdResult> RunAsync(IReadOnlyList<string> args, string workingDirectory, TimeSpan timeout,
        CancellationToken ct, string? inputFile = null)
    {
        ct.ThrowIfCancellationRequested();
        if (timeout <= TimeSpan.Zero)
            throw new ArgumentOutOfRangeException(nameof(timeout), "O tempo limite deve ser positivo.");
        if (!Directory.Exists(workingDirectory))
            throw new IOException("O diretório de trabalho do Docker não existe ou está inacessível.");

        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(timeout);
        var start = new ProcessStartInfo
        {
            FileName = executable ?? FindDocker(),
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            StandardOutputEncoding = Encoding.UTF8,
            RedirectStandardError = true,
            RedirectStandardInput = true,
            StandardInputEncoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false)
        };
        foreach (var arg in args)
            start.ArgumentList.Add(arg);
        // Keep Docker's config directory and selected context, but not endpoint overrides.
        foreach (var key in start.Environment.Keys.ToArray())
            if (key.StartsWith("COMPOSE_", StringComparison.OrdinalIgnoreCase) ||
                key.StartsWith("CASSINO_", StringComparison.OrdinalIgnoreCase) || SecretFile.IsPasswordKey(key) ||
                key.Equals("DOCKER_HOST", StringComparison.OrdinalIgnoreCase) ||
                key.Equals("DOCKER_CONTEXT", StringComparison.OrdinalIgnoreCase) ||
                key.Equals("DOCKER_TLS", StringComparison.OrdinalIgnoreCase) ||
                key.Equals("DOCKER_TLS_VERIFY", StringComparison.OrdinalIgnoreCase) ||
                key.Equals("DOCKER_CERT_PATH", StringComparison.OrdinalIgnoreCase))
                start.Environment.Remove(key);

        using var input = inputFile is null ? null : OpenInput(inputFile, workingDirectory);
        using var process = new Process { StartInfo = start };
        try
        {
            if (deadline.IsCancellationRequested)
            {
                ct.ThrowIfCancellationRequested();
                throw new TimeoutException("Tempo limite excedido ao executar o comando do Docker.");
            }
            if (!process.Start())
                throw new IOException("Não foi possível iniciar a CLI do Docker.");
        }
        catch (Win32Exception ex)
        {
            var message = ex.NativeErrorCode switch
            {
                2 or 3 => "CLI do Docker não encontrada. Confira a instalação e o PATH.",
                var code when code == (OperatingSystem.IsWindows() ? 5 : 13) =>
                    "Acesso negado ao iniciar a CLI do Docker. Verifique as permissões da instalação.",
                _ => $"Não foi possível iniciar a CLI do Docker (erro do sistema {ex.NativeErrorCode})."
            };
            throw new IOException(message);
        }

        var stdout = ReadOutputAsync(process.StandardOutput, deadline.Token);
        var stderr = process.StandardError.BaseStream.CopyToAsync(Stream.Null, deadline.Token);
        var stdin = SendInputAsync(process.StandardInput, input, deadline.Token);
        var exit = process.WaitForExitAsync(deadline.Token);
        var completion = Task.WhenAll(stdout, stderr, stdin, exit);
        try
        {
            await completion.WaitAsync(deadline.Token).ConfigureAwait(false);
            return new CmdResult(process.ExitCode, await stdout.ConfigureAwait(false));
        }
        catch (Exception) when (deadline.IsCancellationRequested)
        {
            await StopAsync(process, completion).ConfigureAwait(false);
            if (ct.IsCancellationRequested)
                throw new OperationCanceledException("Comando do Docker cancelado.", ct);
            throw new TimeoutException("Tempo limite excedido ao executar o comando do Docker.");
        }
        catch (IOException)
        {
            await StopAsync(process, completion).ConfigureAwait(false);
            throw new IOException("Falha de leitura ou escrita nos fluxos da CLI do Docker.");
        }
    }

    private static string FindDocker()
    {
        var name = OperatingSystem.IsWindows() ? "docker.exe" : "docker";
        // Only absolute PATH entries: do not launch a Docker lookalike from the working directory.
        foreach (var entry in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
        {
            var directory = OperatingSystem.IsWindows() ? entry.Trim('"') : entry;
            if (Path.IsPathFullyQualified(directory))
            {
                var candidate = Path.Combine(directory, name);
                if (File.Exists(candidate))
                    return candidate;
            }
        }
        throw new IOException("CLI do Docker não encontrada. Confira a instalação e o PATH.");
    }

    private static FileStream OpenInput(string path, string workingDirectory)
    {
        try
        {
            return new FileStream(Path.GetFullPath(path, Path.GetFullPath(workingDirectory)), FileMode.Open,
                FileAccess.Read, FileShare.Read, 65536, FileOptions.Asynchronous | FileOptions.SequentialScan);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException or NotSupportedException)
        {
            throw new IOException("Não foi possível abrir o arquivo de entrada do Docker.");
        }
    }

    private static async Task SendInputAsync(StreamWriter writer, FileStream? input, CancellationToken ct)
    {
        using var pipe = writer.BaseStream;
        if (input is not null)
        {
            await input.CopyToAsync(pipe, ct).ConfigureAwait(false);
            await pipe.FlushAsync(ct).ConfigureAwait(false);
        }
    }

    private static async Task<string> ReadOutputAsync(StreamReader reader, CancellationToken ct)
    {
        var buffer = new char[8192];
        var output = new StringBuilder();
        var truncated = false;
        int count;
        while ((count = await reader.ReadAsync(buffer.AsMemory(), ct).ConfigureAwait(false)) != 0)
        {
            var retained = Math.Min(count, MaxOutputChars - output.Length);
            output.Append(buffer, 0, retained);
            truncated |= retained != count;
        }
        if (truncated)
        {
            // Do not retain a partial last line: truncating within a password could defeat literal redaction.
            var end = output.Length;
            while (end > 0 && output[end - 1] != '\n')
                end--;
            output.Length = end;
            output.Append("[saída do Docker truncada]\n");
        }
        return output.ToString();
    }

    private static async Task StopAsync(Process process, Task completion)
    {
        try { process.Kill(entireProcessTree: true); }
        catch (InvalidOperationException) { } // Already exited.
        catch (Win32Exception)
        {
            throw new IOException("Não foi possível encerrar a árvore de processos da CLI do Docker.");
        }

        using var cleanup = new CancellationTokenSource(TimeSpan.FromSeconds(3));
        try { await process.WaitForExitAsync(cleanup.Token).ConfigureAwait(false); }
        catch (OperationCanceledException)
        {
            throw new IOException("Não foi possível confirmar o encerramento da CLI do Docker.");
        }
        // Cleanup must not hang on a pipe inherited by a process that outlived the CLI.
        _ = completion.ContinueWith(static task => _ = task.Exception, CancellationToken.None,
            TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
    }
}
