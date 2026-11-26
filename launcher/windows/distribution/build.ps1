#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Iscc,
    [Parameter(Mandatory)][string]$BuildRoot,
    [ValidatePattern('\A(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\z')]
    [string]$Version = '1.0.0',
    [string]$Dotnet = 'dotnet',
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
$windows = Join-Path $repo 'launcher/windows'
$root = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($BuildRoot)
if (@($Version.Split('.') | Where-Object { [int]$_ -gt 65535 }).Count) {
    throw 'Each version component must fit in a Windows file version (0-65535).'
}

function Invoke-Checked([string]$Program, [string[]]$ArgumentList) {
    & $Program @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$(Split-Path -Leaf $Program) exited with code $LASTEXITCODE."
    }
}

$Dotnet = (Get-Command $Dotnet -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$Python = (Get-Command $Python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$compiler = Get-Item -LiteralPath $Iscc
if ($compiler.PSIsContainer -or $compiler.Name -ine 'ISCC.exe' -or $compiler.VersionInfo.ProductName -ne 'Inno Setup') {
    throw 'Expected an Inno Setup ISCC.exe at the explicit path.'
}
$signature = Get-AuthenticodeSignature -LiteralPath $compiler.FullName
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -cnotmatch '(?:^|, )CN=Pyrsys B\.V\.(?:,|$)') {
    throw 'ISCC.exe must have a valid Authenticode signature from the expected Inno Setup publisher (Pyrsys B.V.).'
}
# ISCC 6 can return 1 for its help banner; fail if the compiler is not a supported major version.
$banner = & $compiler.FullName '/?'
if ($LASTEXITCODE -notin @(0, 1) -or ($banner -join "`n") -notmatch 'Inno Setup [67] Command-Line Compiler') {
    throw 'Expected the Inno Setup 6 or 7 command-line compiler.'
}
Write-Host (($banner -join "`n") -split "`n" | Select-String 'Inno Setup [67] Command-Line Compiler' | Select-Object -First 1)
$installer = Join-Path $windows 'installer/build.ps1'
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw 'Missing launcher/windows/installer/build.ps1 (Inno Setup installer contract).'
}
# Never reuse or delete an existing build directory.
New-Item -ItemType Directory -Path $root | Out-Null
$payload = Join-Path $root 'payload'
$output = Join-Path $root 'output'
New-Item -ItemType Directory -Path $payload, $output | Out-Null

Push-Location $repo
try {
    Invoke-Checked $Python @('-m', 'unittest', 'discover', '-s', 'launcher/tests', '-v')
    Invoke-Checked (Get-Command docker -CommandType Application | Select-Object -First 1).Source @('compose', 'version')
    Invoke-Checked $Python @('launcher/windows/integration/test_assets.py')
    Invoke-Checked $Python @('-m', 'unittest', 'discover', '-s', 'launcher/windows/distribution', '-v')
    Push-Location $windows
    try {
        $sdk = & $Dotnet --version
        if ($LASTEXITCODE -ne 0 -or $sdk -ne '10.0.404') { throw 'Expected .NET SDK 10.0.404.' }
        foreach ($suite in @('Core', 'Infrastructure', 'Recovery')) {
            $project = "CassinoLauncher.$suite.Tests"
            Invoke-Checked $Dotnet @('restore', $project)
            Invoke-Checked $Dotnet @('run', '--project', $project, '-c', 'Release', '--no-restore')
        }
        Invoke-Checked $Dotnet @('publish', 'CassinoLauncher', '-c', 'Release', '-r', 'win-x64',
            '--self-contained', 'true', '-p:PublishSingleFile=true', '-p:IncludeNativeLibrariesForSelfExtract=true',
            '-p:DebugType=None', "-p:Version=$Version", '-o', $payload)
    } finally {
        Pop-Location
    }
    Invoke-Checked $Python @('launcher/windows/integration/stage_assets.py', '--output', (Join-Path $payload 'app'))
    $check = Join-Path $PSScriptRoot 'check_package.py'
    Invoke-Checked $Python @($check, 'payload', $payload)
    # A successful script need not set an exit code; reset the native/global status, not a local shadow.
    $global:LASTEXITCODE = 0
    & $installer -Iscc $compiler.FullName -Version $Version -Payload $payload -Output $output
    if ($global:LASTEXITCODE -ne 0) { throw "Installer builder exited with code $global:LASTEXITCODE." }
    Invoke-Checked $Python @($check, 'checksums', $root)
} finally {
    Pop-Location
}
