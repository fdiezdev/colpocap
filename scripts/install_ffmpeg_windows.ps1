[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$FfmpegVersion = "8.1.2"
$ArchiveName = "ffmpeg-$FfmpegVersion-essentials_build.zip"
$ArchiveUrl = "https://www.gyan.dev/ffmpeg/builds/packages/$ArchiveName"
$ExpectedSha256 = "db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$TargetDirectory = Join-Path $ProjectRoot "third_party\ffmpeg\windows-x64"
$TargetExecutable = Join-Path $TargetDirectory "ffmpeg.exe"
$TemporaryDirectory = Join-Path ([System.IO.Path]::GetTempPath()) (
    "colpocap-ffmpeg-" + [System.Guid]::NewGuid().ToString("N")
)
$ArchivePath = Join-Path $TemporaryDirectory $ArchiveName
$ExtractedDirectory = Join-Path $TemporaryDirectory "extracted"

if (-not [Environment]::Is64BitOperatingSystem) {
    throw "ColpoCap requiere Windows de 64 bits para usar esta compilación de FFmpeg."
}

if ((Test-Path -LiteralPath $TargetExecutable) -and -not $Force) {
    Write-Host "FFmpeg ya existe en: $TargetExecutable"
    $ExistingVersion = (& $TargetExecutable -hide_banner -version 2>&1 | Out-String)
    $VersionExitCode = $LASTEXITCODE
    $ExistingDevices = (& $TargetExecutable -hide_banner -devices 2>&1 | Out-String)
    $DevicesExitCode = $LASTEXITCODE
    if (
        $VersionExitCode -ne 0 -or
        $ExistingVersion -notmatch 'ffmpeg version' -or
        $DevicesExitCode -ne 0 -or
        $ExistingDevices -notmatch '(?im)\bdshow\b'
    ) {
        throw "El FFmpeg existente no es válido. Vuelva a ejecutar este script con -Force."
    }
    Write-Host ($ExistingVersion.Trim().Split([Environment]::NewLine)[0])
    Write-Host "La instalación existente es válida. Use -Force si desea reemplazarla."
    return
}

New-Item -ItemType Directory -Path $TemporaryDirectory | Out-Null
New-Item -ItemType Directory -Path $ExtractedDirectory | Out-Null
New-Item -ItemType Directory -Path $TargetDirectory -Force | Out-Null

try {
    Write-Host "Descargando FFmpeg $FfmpegVersion desde Gyan.dev..."
    Invoke-WebRequest -Uri $ArchiveUrl -OutFile $ArchivePath -UseBasicParsing

    $ActualSha256 = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualSha256 -ne $ExpectedSha256) {
        throw (
            "El checksum SHA-256 del archivo descargado no coincide. " +
            "Esperado: $ExpectedSha256. Obtenido: $ActualSha256. No se instalará el binario."
        )
    }

    Write-Host "Checksum verificado. Extrayendo el paquete..."
    Expand-Archive -LiteralPath $ArchivePath -DestinationPath $ExtractedDirectory

    $DownloadedExecutable = Get-ChildItem -Path $ExtractedDirectory -Recurse -File `
        -Filter "ffmpeg.exe" | Select-Object -First 1
    if ($null -eq $DownloadedExecutable) {
        throw "El paquete verificado no contiene ffmpeg.exe."
    }

    Write-Host "Validando el ejecutable descargado..."
    $VersionOutput = (& $DownloadedExecutable.FullName -hide_banner -version 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $VersionOutput -notmatch 'ffmpeg version') {
        throw "El ejecutable descargado no respondió correctamente a -version."
    }

    $DevicesOutput = (& $DownloadedExecutable.FullName -hide_banner -devices 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $DevicesOutput -notmatch '(?im)\bdshow\b') {
        throw "La compilación descargada no informa soporte DirectShow (dshow)."
    }

    $PackageRoot = Split-Path -Parent (Split-Path -Parent $DownloadedExecutable.FullName)
    Copy-Item -LiteralPath $DownloadedExecutable.FullName -Destination $TargetExecutable -Force

    $LicenseFile = Get-ChildItem -LiteralPath $PackageRoot -File |
        Where-Object { $_.Name -match '^LICENSE' } |
        Select-Object -First 1
    if ($null -ne $LicenseFile) {
        Copy-Item -LiteralPath $LicenseFile.FullName `
            -Destination (Join-Path $TargetDirectory $LicenseFile.Name) -Force
    }

    $PackageReadme = Get-ChildItem -LiteralPath $PackageRoot -File |
        Where-Object { $_.Name -match '^README' } |
        Select-Object -First 1
    if ($null -ne $PackageReadme) {
        Copy-Item -LiteralPath $PackageReadme.FullName `
            -Destination (Join-Path $TargetDirectory "FFMPEG-PACKAGE-README.txt") -Force
    }

    @(
        "FFmpeg version: $FfmpegVersion"
        "Build: Gyan FFmpeg essentials_build (Windows x64, GPLv3)"
        "Archive: $ArchiveUrl"
        "Archive SHA-256: $ExpectedSha256"
        "Upstream source: https://github.com/FFmpeg/FFmpeg/commit/38b88335f9"
        "Downloaded: $([DateTimeOffset]::Now.ToString('o'))"
    ) | Set-Content -LiteralPath (Join-Path $TargetDirectory "SOURCE.txt") -Encoding UTF8

    Write-Host ""
    Write-Host "FFmpeg quedó instalado y validado en:"
    Write-Host $TargetExecutable
    Write-Host ""
    Write-Host "La aplicación lo elegirá antes que cualquier FFmpeg presente en PATH."
}
finally {
    if (Test-Path -LiteralPath $TemporaryDirectory) {
        Remove-Item -LiteralPath $TemporaryDirectory -Recurse -Force
    }
}
