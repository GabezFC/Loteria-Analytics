#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Manifest,
    [Parameter(Mandatory)][string]$Signature,
    [Parameter(Mandatory)][string]$TrustedCertificate,
    [Parameter(Mandatory)][string]$Installer,
    [Parameter(Mandatory)][ValidatePattern('\A(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\z')]
    [string]$ExpectedVersion
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSEdition -eq 'Desktop') { Add-Type -AssemblyName System.Security }
else { Add-Type -AssemblyName System.Security.Cryptography.Pkcs }

function Read-BoundedFile([string]$Path, [long]$Limit) {
    $item = Get-Item -LiteralPath $Path
    if ($item -isnot [IO.FileInfo] -or $item.Length -eq 0 -or $item.Length -gt $Limit) {
        throw 'Expected a small local verification input file.'
    }
    return ,([IO.File]::ReadAllBytes($item.FullName))
}

$contents = Read-BoundedFile $Manifest 256
$signatureBytes = Read-BoundedFile $Signature 65536
$certBytes = Read-BoundedFile $TrustedCertificate 65536
$certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new([byte[]]$certBytes, '',
    [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet)
try {
    if ($certificate.HasPrivateKey -or
        [Convert]::ToBase64String($certificate.RawData) -cne [Convert]::ToBase64String($certBytes)) {
        throw 'Provide only the independently trusted public certificate in DER (.cer) format.'
    }
    $now = [DateTime]::UtcNow
    if ($now -lt $certificate.NotBefore.ToUniversalTime() -or $now -gt $certificate.NotAfter.ToUniversalTime()) {
        throw 'Trusted certificate is outside its validity period.'
    }
    $attached = [System.Security.Cryptography.Pkcs.SignedCms]::new()
    $attached.Decode($signatureBytes)
    if ($attached.ContentInfo.Content.Length -ne 0) { throw 'Expected a detached CMS signature.' }
    $cms = [System.Security.Cryptography.Pkcs.SignedCms]::new(
        [System.Security.Cryptography.Pkcs.ContentInfo]::new([byte[]]$contents), $true)
    $cms.Decode($signatureBytes)
    if ($cms.SignerInfos.Count -ne 1) { throw 'Expected exactly one CMS signer.' }
    $signer = $cms.SignerInfos[0]
    if ($signer.DigestAlgorithm.Value -notin @('2.16.840.1.101.3.4.2.1', '2.16.840.1.101.3.4.2.2', '2.16.840.1.101.3.4.2.3')) {
        throw 'Expected SHA-256, SHA-384 or SHA-512 in the CMS signature.'
    }
    if ($null -eq $signer.Certificate -or
        [Convert]::ToBase64String($signer.Certificate.RawData) -cne [Convert]::ToBase64String($certificate.RawData)) {
        throw 'CMS signer does not match the independently trusted certificate.'
    }
    # Exact certificate pin provides trust; this call checks the cryptographic signature.
    $cms.CheckSignature($true)
    $text = [System.Text.Encoding]::ASCII.GetString($contents)
    $pattern = '\ACassino-Version: ([0-9]+\.[0-9]+\.[0-9]+)\r?\nSHA256: ([0-9a-fA-F]{64})\r?\n\z'
    if ($text -cnotmatch $pattern -or $Matches[1] -cne $ExpectedVersion) {
        throw 'Signed manifest format or version does not match the approved update.'
    }
    $expectedHash = $Matches[2]
    if ((Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash -ine $expectedHash) {
        throw 'Installer SHA-256 does not match the signed manifest.'
    }
    Write-Output "Verified installer for version $ExpectedVersion. Nothing has been executed."
} finally {
    $certificate.Dispose()
}
