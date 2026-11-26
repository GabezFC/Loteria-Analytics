using System.IO;
using System.Reflection;
using System.Windows;
using CoreLauncher = CassinoLauncher.Core.Launcher;

namespace CassinoLauncher;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        if (e.Args is ["--version"])
        {
            Console.WriteLine(typeof(App).Assembly
                .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion);
            Shutdown();
            return;
        }

        try
        {
            var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (string.IsNullOrEmpty(localAppData))
            {
                throw new InvalidOperationException("Não foi possível localizar a pasta de dados locais do Windows.");
            }

            var home = Path.Combine(localAppData, "Cassino");
            var assets = Path.Combine(AppContext.BaseDirectory, "app");
            MainWindow = new MainWindow(new CoreLauncher(home, assets));
            MainWindow.Show();
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Não foi possível abrir o launcher.\n\n{ex.Message}",
                "Cassino Launcher", MessageBoxButton.OK, MessageBoxImage.Error);
            Shutdown(1);
        }
    }
}
