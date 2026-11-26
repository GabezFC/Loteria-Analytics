using System.ComponentModel;
using System.Diagnostics;
using System.Windows;
using System.Windows.Documents;
using CassinoLauncher.Core;
using CoreLauncher = CassinoLauncher.Core.Launcher;

namespace CassinoLauncher;

public partial class MainWindow : Window
{
    private readonly CoreLauncher _launcher;
    private CancellationTokenSource? _operation;
    private bool _closeRequested;

    public MainWindow(CoreLauncher launcher)
    {
        _launcher = launcher;
        InitializeComponent();
    }

    private async void Start_Click(object sender, RoutedEventArgs e) =>
        await RunAsync("Iniciando o Cassino…", "Não foi possível concluir a inicialização.",
            StartAndOpenDashboardAsync);

    private async void Stop_Click(object sender, RoutedEventArgs e) =>
        await RunAsync("Parando o Cassino…", "Não foi possível parar o Cassino.",
            async (progress, ct) =>
            {
                InvalidateStatus();
                await Task.Run(() => _launcher.StopAsync(progress, ct), ct);
                return "Cassino parado.";
            });

    private async void Restart_Click(object sender, RoutedEventArgs e) =>
        await RunAsync("Parando o Cassino para reiniciar…", "Não foi possível concluir o reinício.",
            async (progress, ct) =>
            {
                InvalidateStatus();
                await Task.Run(() => _launcher.StopAsync(progress, ct), ct);
                ct.ThrowIfCancellationRequested();
                OperationText.Text = "Iniciando novamente…";
                return await StartAndOpenDashboardAsync(progress, ct);
            });

    private async Task<string> StartAndOpenDashboardAsync(IProgress<string> progress, CancellationToken ct)
    {
        InvalidateStatus();
        await Task.Run(() => _launcher.StartAsync(progress, ct), ct);
        try
        {
            await OpenHealthyDashboardAsync(ct);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            throw new InvalidOperationException(
                $"A inicialização terminou, mas o dashboard não foi aberto. {ex.Message}", ex);
        }

        return "Cassino iniciado. Dashboard aberto no navegador.";
    }

    private async void Dashboard_Click(object sender, RoutedEventArgs e) =>
        await RunAsync("Verificando o dashboard…", "Não foi possível abrir o dashboard.",
            async (_, ct) =>
            {
                await OpenHealthyDashboardAsync(ct);
                return "Dashboard aberto no navegador.";
            });

    private async Task OpenHealthyDashboardAsync(CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        OperationText.Text = "Verificando a saúde do dashboard…";
        var healthy = await Task.Run(() => _launcher.HealthAsync(ct), ct);
        ct.ThrowIfCancellationRequested();
        if (!healthy)
        {
            throw new InvalidOperationException(
                "O dashboard ainda não está saudável. Inicie o Cassino ou consulte o status e os logs antes de tentar novamente.");
        }

        await Task.Run(() => OpenInBrowser(_launcher.Dashboard, ct), ct);
    }

    private async void Status_Click(object sender, RoutedEventArgs e) =>
        await RunAsync("Consultando os serviços…", "Não foi possível consultar o status.",
            async (_, ct) =>
            {
                InvalidateStatus();
                var services = await Task.Run(() => _launcher.StatusAsync(ct), ct);
                ct.ThrowIfCancellationRequested();
                ServicesGrid.ItemsSource = services.Select(service => new ServiceStatus(service.Service,
                    TranslateStatus(service.State), TranslateStatus(service.Health))).ToArray();
                StatusHint.Text = services.Count == 0 ? "Nenhum serviço retornado." : "Última atualização: " + DateTime.Now.ToString("HH:mm:ss");
                return "Status consultado.";
            });

    private async void Logs_Click(object sender, RoutedEventArgs e) =>
        await RunAsync("Carregando os logs…", "Não foi possível carregar os logs.",
            async (_, ct) =>
            {
                var logs = await Task.Run(() => _launcher.LogsAsync(ct), ct);
                ct.ThrowIfCancellationRequested();
                LogsText.Text = string.IsNullOrWhiteSpace(logs) ? "Nenhum registro disponível." : logs;
                return "Logs atualizados.";
            });

    private async void Backup_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new Microsoft.Win32.OpenFolderDialog { Title = "Escolha uma pasta privada para o backup" };
        if (dialog.ShowDialog(this) != true) return;
        await RunAsync("Criando e verificando em PostgreSQL isolado…", "Não foi possível concluir o backup.",
            async (_, ct) => $"Backup verificado: {(await Task.Run(() => _launcher.BackupAsync(dialog.FolderName, ct), ct)).Directory}");
    }

    private async void VerifyBackup_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new Microsoft.Win32.OpenFolderDialog { Title = "Escolha a pasta de um backup confiável" };
        if (dialog.ShowDialog(this) != true || MessageBox.Show(this,
                "Verificar este backup confiável em um banco descartável? O banco ativo não será alterado.",
                "Verificar backup", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No) != MessageBoxResult.Yes) return;
        await RunAsync("Verificando em PostgreSQL isolado…", "Não foi possível verificar o backup.",
            async (_, ct) => $"Backup verificado: {(await Task.Run(() => _launcher.VerifyBackupAsync(dialog.FolderName, ct), ct)).Directory}");
    }

    private async void DockerHelp_Click(object sender, RoutedEventArgs e) =>
        await RunAsync("Abrindo a documentação do Docker…", "Não foi possível abrir a documentação do Docker.",
            async (_, ct) =>
            {
                var uri = ((Hyperlink)sender).NavigateUri;
                await Task.Run(() => OpenInBrowser(uri, ct), ct);
                return "Documentação aberta no navegador.";
            });

    private async Task RunAsync(string initial, string failure, Func<IProgress<string>, CancellationToken, Task<string>> action)
    {
        if (_operation is not null || _closeRequested)
        {
            return;
        }

        using var operation = new CancellationTokenSource();
        _operation = operation;
        SetBusy(true);
        OperationText.Text = initial;
        OperationError.Clear();
        OperationError.Visibility = Visibility.Collapsed;
        IProgress<string> progress = new Progress<string>(message =>
        {
            if (ReferenceEquals(_operation, operation) && !operation.IsCancellationRequested)
            {
                OperationText.Text = message;
            }
        });

        try
        {
            var result = await action(progress, operation.Token);
            operation.Token.ThrowIfCancellationRequested();
            OperationText.Text = result;
        }
        catch (OperationCanceledException) when (operation.IsCancellationRequested)
        {
            OperationText.Text = "Operação cancelada.";
            ShowError("O cancelamento não desfaz etapas já concluídas. Consulte o status para verificar os serviços.");
        }
        catch (Exception ex)
        {
            OperationText.Text = failure;
            ShowError(ex.Message);
        }
        finally
        {
            _operation = null;
            SetBusy(false);
            if (_closeRequested)
            {
                _ = Dispatcher.BeginInvoke(new Action(Close));
            }
        }
    }

    private void SetBusy(bool busy)
    {
        StartButton.IsEnabled = StopButton.IsEnabled = RestartButton.IsEnabled = DashboardButton.IsEnabled =
            StatusButton.IsEnabled = LogsButton.IsEnabled = BackupButton.IsEnabled = VerifyBackupButton.IsEnabled =
            DockerHelpLink.IsEnabled = !busy && !_closeRequested;
        CancelButton.IsEnabled = busy;
        OperationProgress.IsIndeterminate = busy;
        OperationProgress.Visibility = busy ? Visibility.Visible : Visibility.Collapsed;
    }

    private void InvalidateStatus()
    {
        ServicesGrid.ItemsSource = null;
        StatusHint.Text = "Use Atualizar status para consultar os serviços.";
    }

    private void ShowError(string message)
    {
        OperationError.Text = message;
        OperationError.Visibility = Visibility.Visible;
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => RequestCancellation();

    private void RequestCancellation()
    {
        if (_operation is not { IsCancellationRequested: false } operation)
        {
            return;
        }

        CancelButton.IsEnabled = false;
        OperationText.Text = "Cancelando…";
        try
        {
            operation.Cancel();
        }
        catch (AggregateException)
        {
            ShowError("Falha ao solicitar o cancelamento. Aguarde o término da operação.");
        }
    }

    protected override void OnClosing(CancelEventArgs e)
    {
        base.OnClosing(e);
        if (_operation is not null)
        {
            e.Cancel = true;
            _closeRequested = true;
            RequestCancellation();
        }
    }

    private static void OpenInBrowser(Uri uri, CancellationToken ct)
    {
        if (!uri.IsAbsoluteUri || uri.Scheme is not ("https" or "http"))
        {
            throw new InvalidOperationException("O endereço do navegador deve ser HTTP ou HTTPS.");
        }

        ct.ThrowIfCancellationRequested();
        using var process = Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
    }

    private static string TranslateStatus(string value) => value switch
    {
        "running" => "Em execução",
        "created" => "Criado",
        "exited" => "Encerrado",
        "dead" => "Inativo",
        "restarting" => "Reiniciando",
        "paused" => "Pausado",
        "removing" => "Removendo",
        "healthy" => "Saudável",
        "unhealthy" => "Não saudável",
        "starting" => "Inicializando",
        "" => "—",
        _ => value
    };
}
