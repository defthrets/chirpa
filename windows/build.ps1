<#
.SYNOPSIS
    Build a fully self-contained Windows installer for Chirpa.

.DESCRIPTION
    Produces a single ChirpaSetup.exe that bundles EVERYTHING needed to run:
      * A private, embedded Python runtime (no system Python required)
      * ffmpeg / ffprobe (for RTSP stream verification in the camera wizard)
      * The Chirpa app (birdnet_gui.py) and chart.min.js

    The script:
      1. Downloads the Python embeddable package and ffmpeg "essentials" build.
      2. Stages them next to the app in a self-contained folder layout.
      3. Compiles the Inno Setup script (chirpa.iss) into ChirpaSetup.exe.

    Nothing is installed on the build machine except Inno Setup (the compiler).

.PREREQUISITES
    * Windows 10/11 (or Windows Server) with PowerShell 5+.
    * Inno Setup 6 installed (https://jrsoftware.org/isdl.php). The compiler
      ISCC.exe is auto-detected in the usual Program Files locations, or pass
      -IsccPath.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File build.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File build.ps1 -PythonVersion 3.11.9
#>
[CmdletBinding()]
param(
    [string]$PythonVersion = "3.11.9",
    [ValidateSet("amd64", "arm64")]
    [string]$Arch = "amd64",
    # ffmpeg essentials build (static, includes ffprobe.exe + ffmpeg.exe)
    [string]$FfmpegUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    [string]$IsccPath = ""
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ── Paths ────────────────────────────────────────────────────────────
$Here     = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot = Split-Path -Parent $Here
$Work     = Join-Path $Here "build"
$Staging  = Join-Path $Work "staging"           # becomes the installed {app}
$Cache    = Join-Path $Work "cache"             # downloaded archives
$OutDir   = Join-Path $Here "dist"

function Write-Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }

# ── Fresh staging ────────────────────────────────────────────────────
Write-Step "Preparing folders"
if (Test-Path $Staging) { Remove-Item $Staging -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Staging, $Cache, $OutDir | Out-Null

# ── 1. App files ─────────────────────────────────────────────────────
Write-Step "Staging Chirpa app files"
Copy-Item (Join-Path $RepoRoot "birdnet_gui.py") $Staging
Copy-Item (Join-Path $RepoRoot "chart.min.js")   $Staging
# Note: the repo README is intentionally NOT bundled — the shipped app stays
# free of source-repo URLs and developer-facing docs.

# ── 2. Embedded Python ───────────────────────────────────────────────
Write-Step "Downloading embedded Python $PythonVersion ($Arch)"
$pyZipName = "python-$PythonVersion-embed-$Arch.zip"
$pyUrl     = "https://www.python.org/ftp/python/$PythonVersion/$pyZipName"
$pyZip     = Join-Path $Cache $pyZipName
if (-not (Test-Path $pyZip)) {
    Invoke-WebRequest -Uri $pyUrl -OutFile $pyZip
}
$pyDir = Join-Path $Staging "python"
New-Item -ItemType Directory -Force -Path $pyDir | Out-Null
Expand-Archive -Path $pyZip -DestinationPath $pyDir -Force

# Enable `import site` so the stdlib resolves cleanly when we run scripts.
$pth = Get-ChildItem $pyDir -Filter "python*._pth" | Select-Object -First 1
if ($pth) {
    $content = Get-Content $pth.FullName
    $content = $content -replace '^#\s*import site', 'import site'
    if ($content -notcontains "import site") { $content += "import site" }
    Set-Content $pth.FullName $content
}

# ── 3. ffmpeg / ffprobe ──────────────────────────────────────────────
Write-Step "Downloading ffmpeg (ffprobe for RTSP verification)"
$ffZip = Join-Path $Cache "ffmpeg-essentials.zip"
if (-not (Test-Path $ffZip)) {
    Invoke-WebRequest -Uri $FfmpegUrl -OutFile $ffZip
}
$ffTmp = Join-Path $Work "ffmpeg-extract"
if (Test-Path $ffTmp) { Remove-Item $ffTmp -Recurse -Force }
Expand-Archive -Path $ffZip -DestinationPath $ffTmp -Force
$ffBinSrc = Get-ChildItem $ffTmp -Recurse -Filter "ffprobe.exe" | Select-Object -First 1
if (-not $ffBinSrc) { throw "ffprobe.exe not found in the ffmpeg archive." }
$ffBinDst = Join-Path $Staging "ffmpeg\bin"
New-Item -ItemType Directory -Force -Path $ffBinDst | Out-Null
Copy-Item (Join-Path $ffBinSrc.DirectoryName "ffprobe.exe") $ffBinDst
Copy-Item (Join-Path $ffBinSrc.DirectoryName "ffmpeg.exe")  $ffBinDst -ErrorAction SilentlyContinue

# ── 4. Launcher ──────────────────────────────────────────────────────
Write-Step "Adding launcher"
Copy-Item (Join-Path $Here "Chirpa.cmd") $Staging

# ── 5. Compile installer ─────────────────────────────────────────────
Write-Step "Locating Inno Setup compiler (ISCC.exe)"
if (-not $IsccPath) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )
    $IsccPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $IsccPath -or -not (Test-Path $IsccPath)) {
    Write-Warning "Inno Setup (ISCC.exe) not found. Staging is ready at:`n  $Staging"
    Write-Warning "Install Inno Setup 6 from https://jrsoftware.org/isdl.php, then re-run, or compile chirpa.iss manually."
    exit 2
}

Write-Step "Compiling ChirpaSetup.exe"
& $IsccPath `
    "/DStagingDir=$Staging" `
    "/DOutputDir=$OutDir" `
    (Join-Path $Here "chirpa.iss")

Write-Host "`nDone. Installer is in: $OutDir" -ForegroundColor Green
