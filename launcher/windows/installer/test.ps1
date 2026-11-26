[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Iscc,
    [Parameter(Mandatory)][string]$Payload,
    [string]$Scratch = [IO.Path]::GetTempPath()
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Run-Exe([string]$Exe, [string[]]$Arguments, [string]$WorkingDirectory) {
    $process = Start-Process -FilePath $Exe -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -Wait -PassThru
    Assert ($process.ExitCode -eq 0) "$(Split-Path -Leaf $Exe) exited $($process.ExitCode)."
}

$build = Join-Path $PSScriptRoot 'build.ps1'
Assert (Test-Path -LiteralPath $build -PathType Leaf) 'Installer build entry point is missing.'
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
Assert (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Run fixture as a non-elevated user.'
$allow = @(
    'CassinoLauncher.exe'
    'app\compose.yaml'
    'app\compose.admin.yaml'
    'app\infra\postgres\001-base.sh'
    'app\infra\postgres\002-ingest.sql'
    'app\infra\postgres\003-premios-divergencias-jobs.sql'
    'app\infra\postgres\004-collector-status.sql'
    'app\infra\postgres\005-probabilidades-estatistica.sql'
    'app\infra\postgres\006-experimentos-sugestoes.sql'
    'app\lan\bootstrap.py'
    'app\lan\compose.lan.yaml'
    'app\lan\compose.local.yaml'
    'app\lan\local.conf'
    'app\lan\proxy.inc'
    'app\lan\README.md'
    'app\lan\tls.conf.template'
)
$root = Join-Path (Resolve-Path -LiteralPath $Scratch).ProviderPath ('Cassino Installer Fixture ' + [guid]::NewGuid())
$inputDir = Join-Path $root 'input'
$output = Join-Path $root 'dist'
$installed = Join-Path $root 'installed fixture'
$uninstaller = Join-Path $installed 'unins000.exe'
$local = [Environment]::GetFolderPath('LocalApplicationData')
$defaultFixtureDir = Join-Path $local 'Programs\Cassino Installer Fixture'
$key = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\Cassino.Launcher.InstallerFixture_is1'
$userKey = "HKCU:\$key"
$machineKey = "HKLM:\$key"
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'Cassino Installer Fixture.lnk'
foreach ($path in @($root, $defaultFixtureDir, $userKey, $machineKey, $shortcut)) {
    Assert (-not (Test-Path -LiteralPath $path)) "Fixture path or registration already exists: $path"
}
$silent = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
$oldTemp = $env:TEMP
$oldTmp = $env:TMP
try {
    $null = New-Item -ItemType Directory -Path $root
    $env:TEMP = $root
    $env:TMP = $root
    # Copy only known good files. Never read or copy real secrets from the source tree.
    foreach ($relative in $allow) {
        $target = Join-Path $inputDir $relative
        [void][IO.Directory]::CreateDirectory((Split-Path -Parent $target))
        Copy-Item -LiteralPath (Join-Path $Payload $relative) -Destination $target
    }
    foreach ($relative in @('.env', '.env.consoles', 'CassinoLauncher.pdb', 'app\.env', 'app\dump.sql', 'app\launcher.log', 'app\infra\postgres\007-unexpected.sql', 'app\lan\private.key')) {
        Set-Content -LiteralPath (Join-Path $inputDir $relative) -Value 'synthetic-not-a-secret' -Encoding Ascii
    }

    $required = Join-Path $inputDir 'app\compose.yaml'
    Move-Item -LiteralPath $required -Destination "$required.hold"
    $failure = $null
    try { & $build -Iscc $Iscc -Version 1.0.0 -Payload $inputDir -Output $output -Fixture }
    catch { $failure = $_ }
    finally { Move-Item -LiteralPath "$required.hold" -Destination $required }
    Assert ($null -ne $failure -and $failure.Exception.Message -like '*Required payload file*') 'Missing required asset was not rejected.'
    Assert (-not (Test-Path -LiteralPath $output)) 'Missing-asset build emitted output.'
    Write-Host 'PASS: incomplete payload is rejected before output.'

    & $build -Iscc $Iscc -Version 1.0.0 -Payload $inputDir -Output $output -Fixture
    $setup = Join-Path $output 'Cassino-Setup.exe'
    $sum = (Get-FileHash -LiteralPath $setup).Hash.ToLowerInvariant()
    Assert ((Get-Content -LiteralPath (Join-Path $output 'SHA256SUMS.txt') -Raw).Trim() -ceq "$sum  Cassino-Setup.exe") 'Setup checksum mismatch.'

    # Simulated user data is outside the install directory, not the real Cassino data path.
    $sentinel = Join-Path $root 'user configuration.txt'
    Set-Content -LiteralPath $sentinel -Value 'fixture-data' -Encoding Ascii
    $sentinelHash = (Get-FileHash -LiteralPath $sentinel).Hash
    $installStarted = $true
    Run-Exe $setup ($silent + @('/SP-', "/DIR=`"$installed`"", "/LOG=`"$root\install.log`"")) $root
    $registration = Get-ItemProperty -LiteralPath $userKey
    Assert ($registration.DisplayVersion -eq '1.0.0') 'Fixture version not registered in HKCU.'
    Assert ($registration.InstallLocation.TrimEnd('\') -eq $installed) 'Fixture install path mismatch.'
    Assert (-not (Test-Path -LiteralPath $machineKey)) 'Unexpected machine-wide fixture registration.'
    Assert (Test-Path -LiteralPath $shortcut -PathType Leaf) 'Start Menu shortcut missing.'
    $app = Join-Path $installed 'CassinoLauncher.exe'
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
    Assert ($link.TargetPath -eq $app -and $link.WorkingDirectory -eq $installed) 'Shortcut target or working directory mismatch.'
    $actual = @(Get-ChildItem -LiteralPath $installed -File -Recurse -Force | ForEach-Object { $_.FullName.Substring($installed.Length + 1) })
    $expected = $allow + @('unins000.exe', 'unins000.dat')
    Assert (-not (Compare-Object $expected $actual)) 'Installed files differ from the exact allowlist plus Inno uninstall files.'
    foreach ($relative in $allow) {
        Assert ((Get-FileHash -LiteralPath (Join-Path $inputDir $relative)).Hash -eq (Get-FileHash -LiteralPath (Join-Path $installed $relative)).Hash) "Payload hash mismatch: $relative"
    }
    # --version exits before initializing LocalAppData or the Docker-facing launcher.
    Run-Exe $app @('--version') $root
    Write-Host "PASS: per-user fixture install, version, shortcut, checksum, $($allow.Count) allowlisted hashes, forbidden extras absent, external --version smoke."

    $foreign = Join-Path $installed 'not-owned.txt'
    Set-Content -LiteralPath $foreign -Value 'fixture-foreign-file' -Encoding Ascii
    Run-Exe $uninstaller ($silent + @("/LOG=`"$root\uninstall.log`"")) $root
    Assert (-not (Test-Path -LiteralPath $userKey)) 'Fixture uninstall registration left behind.'
    Assert (-not (Test-Path -LiteralPath $shortcut)) 'Fixture shortcut left behind.'
    $remaining = @(Get-ChildItem -LiteralPath $installed -Force)
    Assert ($remaining.Count -eq 1 -and $remaining[0].FullName -eq $foreign) 'Uninstall must remove all owned files and retain the unowned sentinel.'
    Assert ((Get-FileHash -LiteralPath $sentinel).Hash -eq $sentinelHash) 'Uninstall changed the external user-data sentinel.'
    Write-Host 'PASS: fixture uninstall removed installed files, shortcut and HKCU entry; both data sentinels survived.'
} catch {
    Write-Warning "Fixture evidence retained at $root"
    if ((Get-Variable -Name installStarted -ErrorAction SilentlyContinue) -and (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
        Run-Exe $uninstaller $silent $root
    }
    throw
} finally {
    $env:TEMP = $oldTemp
    $env:TMP = $oldTmp
}
Remove-Item -LiteralPath $root -Recurse -Force
