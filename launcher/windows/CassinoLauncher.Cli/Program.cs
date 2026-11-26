using CassinoLauncher.Core;

if (args.Length is not (5 or 6) || args[0] != "--home" || args[2] != "--assets" ||
    ((args[4] is "backup" or "verify-backup") != (args.Length == 6)))
{
    Console.Error.WriteLine("Uso: CassinoLauncher.Cli --home CAMINHO --assets CAMINHO start|stop|status|health|logs|backup PASTA|verify-backup PASTA");
    return 2;
}
using var cancel = new CancellationTokenSource();
Console.CancelKeyPress += (_, e) => { e.Cancel = true; cancel.Cancel(); };
try
{
    var launcher = new Launcher(args[1], args[3]);
    var ct = cancel.Token;
    switch (args[4])
    {
        case "start": await launcher.StartAsync(new ConsoleProgress(), ct); break;
        case "stop": await launcher.StopAsync(new ConsoleProgress(), ct); break;
        case "status": Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(await launcher.StatusAsync(ct))); break;
        case "health": return await launcher.HealthAsync(ct) ? 0 : 1;
        case "logs": Console.WriteLine(await launcher.LogsAsync(ct)); break;
        case "backup": Console.WriteLine((await launcher.BackupAsync(args[5], ct)).Directory); break;
        case "verify-backup": Console.WriteLine((await launcher.VerifyBackupAsync(args[5], ct)).Directory); break;
        default: return 2;
    }
    return 0;
}
catch (OperationCanceledException) { Console.Error.WriteLine("Operação cancelada."); return 130; }
catch (Exception e) when (e is InvalidOperationException or TimeoutException) { Console.Error.WriteLine(e.Message); return 1; }
catch (Exception) { Console.Error.WriteLine("Falha inesperada ao acessar recursos do launcher."); return 1; }

sealed class ConsoleProgress : IProgress<string> { public void Report(string value) => Console.WriteLine(value); }
