[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Iscc,
    [Parameter(Mandatory)][string]$Version,
    [Parameter(Mandatory)][string]$Payload,
    [Parameter(Mandatory)][string]$Output,
    [switch]$Fixture
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($Version -cnotmatch '^(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\z') {
    throw 'Version must be X.Y.Z, optionally with a prerelease and build metadata.'
}
$numeric = $Matches[1..3] -join '.'
foreach ($number in $numeric.Split('.')) {
    if ([int]$number -gt 65535) { throw 'Each numeric version component must be at most 65535.' }
}
$compiler = (Get-Item -LiteralPath $Iscc).FullName
$source = Get-Item -LiteralPath $Payload
$outDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Output)
$prefix = $source.FullName.TrimEnd('\') + '\'
if (($outDir.TrimEnd('\') + '\').StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Output must not be in the payload directory.'
}

# Exact staged desktop layout; sync with integration/stage_assets.py on asset changes.
# No recursion, globs, or file discovery from the source payload.
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
function Assert-PayloadNode([IO.FileSystemInfo]$Item, [bool]$Directory) {
    if ($Item.PSIsContainer -ne $Directory -or ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Expected an ordinary payload $(if ($Directory) { 'directory' } else { 'file' }): $($Item.FullName)"
    }
}
Assert-PayloadNode $source $true
foreach ($relative in $allow) {
    $path = $source.FullName
    $parts = $relative.Split('\')
    for ($i = 0; $i -lt $parts.Length; $i++) {
        $path = Join-Path $path $parts[$i]
        $directory = $i -lt $parts.Length - 1
        $item = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        if ($null -eq $item) { throw "Required payload file is missing: $relative" }
        Assert-PayloadNode $item $directory
    }
    if ($item.Length -eq 0) { throw "Required payload file is empty: $relative" }
}

$temp = Join-Path ([IO.Path]::GetTempPath()) ('Cassino installer build ' + [guid]::NewGuid())
[void][IO.Directory]::CreateDirectory($temp)
try {
    $stage = Join-Path $temp 'payload'
    $entries = foreach ($relative in $allow) {
        $target = Join-Path $stage $relative
        [void][IO.Directory]::CreateDirectory((Split-Path -Parent $target))
        Copy-Item -LiteralPath (Join-Path $source.FullName $relative) -Destination $target
        $subdir = Split-Path -Parent $relative
        $dest = if ($subdir) { "{app}\$subdir" } else { '{app}' }
        'Source: "{0}"; DestDir: "{1}"; Flags: ignoreversion' -f $relative, $dest
    }
    Set-Content -LiteralPath (Join-Path $temp 'CassinoPayload.iss') -Value $entries -Encoding Ascii
    $arguments = @('--quiet', '--no-ide-signtools', "-I$temp", "-O$temp", "-DPayloadRoot=$stage", "-DReleaseVersion=$Version", "-DNumericVersion=$numeric")
    if ($Fixture) { $arguments += '-DFixtureBuild' }
    $arguments += Join-Path $PSScriptRoot 'Cassino.iss'
    & $compiler @arguments
    if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE." }

    $name = 'Cassino-Setup.exe'
    $setup = Join-Path $temp $name
    $hash = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifest = Join-Path $temp 'SHA256SUMS.txt'
    [IO.File]::WriteAllText($manifest, "$hash  $name`n", [Text.Encoding]::ASCII)
    [void][IO.Directory]::CreateDirectory($outDir)
    Copy-Item -LiteralPath $setup -Destination (Join-Path $outDir $name) -Force
    Copy-Item -LiteralPath $manifest -Destination (Join-Path $outDir 'SHA256SUMS.txt') -Force
    Write-Host "Built $(Join-Path $outDir $name) (SHA-256 $hash)"
} finally {
    Remove-Item -LiteralPath $temp -Recurse -Force
}
