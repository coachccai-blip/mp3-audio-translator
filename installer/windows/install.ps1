# Installateur Doublr pour Windows 10/11.
# Lancé par Installer-Doublr.bat. Relancer ce script met Doublr à jour (vos clés et projets sont conservés).
# Tout est installé dans %LOCALAPPDATA%\Doublr, sans droits administrateur.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo   = 'coachccai-blip/mp3-audio-translator'
$Branch = if ($env:DOUBLR_BRANCH) { $env:DOUBLR_BRANCH } else { 'main' }
# DOUBLR_NONINTERACTIVE=1 : aucune question (tests automatisés sur GitHub Actions).
$NonInteractive = $env:DOUBLR_NONINTERACTIVE -eq '1'
$Root   = Join-Path $env:LOCALAPPDATA 'Doublr'
$App    = Join-Path $Root 'app'
$Tools  = Join-Path $Root 'tools'
$Log    = Join-Path $Root 'install.log'
$Total  = 8

New-Item -ItemType Directory -Force -Path $Root, $Tools | Out-Null
"=== Installation $(Get-Date) ===" | Out-File -FilePath $Log -Append -Encoding utf8

function Step([int]$n, [string]$msg) { Write-Host ''; Write-Host "[$n/$Total] $msg" -ForegroundColor Green }
function Info([string]$msg) { Write-Host "      $msg" }
function Fail([string]$msg) {
    Write-Host ''
    Write-Host "ERREUR : $msg" -ForegroundColor Red
    Write-Host "Détails dans le journal : $Log" -ForegroundColor Yellow
    if (-not $NonInteractive) { Read-Host 'Appuyez sur Entrée pour fermer' }
    exit 1
}
function Invoke-Logged([string]$exe, [string[]]$ArgList, [string]$what) {
    # PowerShell 5 transforme la sortie d'erreur des programmes en exceptions : on la journalise sans s'arrêter.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $exe @ArgList 2>&1 | Out-File -FilePath $Log -Append -Encoding utf8
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($code -ne 0) { Fail "$what a échoué (code $code)." }
}
function Get-File([string]$url, [string]$dest) {
    try { Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing }
    catch { Fail "Téléchargement impossible : $url ($($_.Exception.Message))" }
}

Write-Host ''
Write-Host '  Doublr — installation' -ForegroundColor Cyan
Write-Host '  Doublage audio par IA, voix natives, durée identique.'
Write-Host "  Dossier : $Root"
Write-Host '  Durée : 15 à 40 minutes selon votre connexion (environ 6 Go à télécharger).'

# --- 1. Python ----------------------------------------------------------------
Step 1 'Python 3.11'
$Py = $null
foreach ($v in '3.11', '3.12') {
    try {
        $exe = & py "-$v" -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { $Py = $exe.Trim(); break }
    } catch { }
}
$LocalPy = Join-Path $Tools 'python\python.exe'
if (-not $Py -and (Test-Path $LocalPy)) { $Py = $LocalPy }
if (-not $Py) {
    Info 'Téléchargement de Python 3.11.9…'
    $inst = Join-Path $env:TEMP 'python-3.11.9-amd64.exe'
    Get-File 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' $inst
    Info 'Installation de Python (sans droits administrateur)…'
    $p = Start-Process -FilePath $inst -Wait -PassThru -ArgumentList @(
        '/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'Include_launcher=0', 'Include_test=0',
        'Include_doc=0', 'Shortcuts=0', "TargetDir=$(Join-Path $Tools 'python')")
    if ($p.ExitCode -ne 0 -or -not (Test-Path $LocalPy)) { Fail "L'installation de Python a échoué (code $($p.ExitCode))." }
    $Py = $LocalPy
}
Info "Python : $Py"

# --- 2. Node.js (pour construire l'interface) -----------------------------------
Step 2 'Node.js'
$NodeDir = Join-Path $Tools 'node'
if (-not (Test-Path (Join-Path $NodeDir 'node.exe'))) {
    $rel = (Invoke-RestMethod -Uri 'https://nodejs.org/dist/index.json' -UseBasicParsing) |
        Where-Object { $_.version -like 'v22.*' } | Select-Object -First 1
    if (-not $rel) { Fail 'Impossible de trouver la version de Node.js à télécharger.' }
    $zipName = "node-$($rel.version)-win-x64"
    Info "Téléchargement de Node.js $($rel.version)…"
    $zip = Join-Path $env:TEMP "$zipName.zip"
    Get-File "https://nodejs.org/dist/$($rel.version)/$zipName.zip" $zip
    Expand-Archive -Path $zip -DestinationPath $Tools -Force
    if (Test-Path $NodeDir) { Remove-Item -Recurse -Force $NodeDir }
    Rename-Item -Path (Join-Path $Tools $zipName) -NewName 'node'
}
$env:Path = "$NodeDir;$env:Path"
Info "Node.js : $(& (Join-Path $NodeDir 'node.exe') --version)"

# --- 3. Application ---------------------------------------------------------------
Step 3 "Téléchargement de Doublr ($Branch)"
$zip = Join-Path $env:TEMP 'doublr-src.zip'
$tmp = Join-Path $env:TEMP 'doublr-src'
Get-File "https://codeload.github.com/$Repo/zip/refs/heads/$Branch" $zip
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$src = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
New-Item -ItemType Directory -Force -Path $App | Out-Null
# Mise à jour du code en conservant clés, données, exports, environnement Python et dépendances.
$ErrorActionPreference = 'Continue'
& robocopy $src.FullName $App /MIR /NFL /NDL /NJH /NJS /NP `
    /XD (Join-Path $App '.venv') (Join-Path $App 'data') (Join-Path $App 'exports') (Join-Path $App 'frontend\node_modules') `
    /XF (Join-Path $App '.env') 2>&1 | Out-File -FilePath $Log -Append -Encoding utf8
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($code -ge 8) { Fail "Copie des fichiers impossible (robocopy $code)." }
Info "Installé dans $App"

# --- 4. Environnement Python + modèles d'IA ------------------------------------------
Step 4 'Bibliothèques d''IA (PyTorch, Whisper, Demucs, pyannote)'
$Venv = Join-Path $App '.venv'
$VPy  = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $VPy)) { Invoke-Logged $Py @('-m', 'venv', $Venv) 'La création de l''environnement Python' }
Invoke-Logged $VPy @('-m', 'pip', 'install', '--upgrade', 'pip') 'La mise à jour de pip'

$Gpu = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'NVIDIA' }).Count -gt 0
if ($Gpu) { $TorchIndex = 'https://download.pytorch.org/whl/cu121'; Info 'Carte graphique NVIDIA détectée : version GPU de PyTorch.' }
else      { $TorchIndex = 'https://download.pytorch.org/whl/cpu';   Info 'Pas de carte NVIDIA : version processeur (CPU) de PyTorch.' }
Info 'Téléchargement de PyTorch (plusieurs minutes)…'
Invoke-Logged $VPy @('-m', 'pip', 'install', 'torch==2.5.1', 'torchaudio==2.5.1', '--index-url', $TorchIndex) 'L''installation de PyTorch'
Info 'Installation de Doublr et de ses dépendances…'
Invoke-Logged $VPy @('-m', 'pip', 'install', '-e', "$(Join-Path $App 'backend')[ai]", 'reportlab') 'L''installation des dépendances'

# --- 5. Interface -------------------------------------------------------------------
Step 5 'Construction de l''interface'
Push-Location (Join-Path $App 'frontend')
$env:VITE_SAME_ORIGIN = '1'
Invoke-Logged 'npm.cmd' @('ci', '--no-audit', '--no-fund') 'L''installation des paquets de l''interface'
Invoke-Logged 'npm.cmd' @('run', 'build') 'La construction de l''interface'
Remove-Item Env:\VITE_SAME_ORIGIN
Pop-Location

# --- 6. Modèles ------------------------------------------------------------------------
Step 6 'Téléchargement des modèles (Whisper large-v3 ≈ 3 Go, Demucs ≈ 80 Mo)'
# (Script Python dédié : PowerShell 5 retire les guillemets des arguments passés à un programme.)
Invoke-Logged $VPy @((Join-Path $App 'scripts\download_models.py')) 'Le téléchargement des modèles'

# --- 7. Clés API -------------------------------------------------------------------------
Step 7 'Configuration'
$EnvFile = Join-Path $App '.env'
if (-not (Test-Path $EnvFile)) { Copy-Item (Join-Path $App '.env.example') $EnvFile }
function Set-EnvValue([string]$key, [string]$value) {
    $lines = [System.Collections.Generic.List[string]](Get-Content -Path $EnvFile -Encoding UTF8)
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*$([regex]::Escape($key))\s*=") { $lines[$i] = "$key=$value"; $found = $true }
    }
    if (-not $found) { $lines.Add("$key=$value") }
    [IO.File]::WriteAllLines($EnvFile, $lines, (New-Object Text.UTF8Encoding $false))
}
function Get-EnvValue([string]$key) {
    foreach ($l in Get-Content -Path $EnvFile -Encoding UTF8) {
        if ($l -match "^\s*$([regex]::Escape($key))\s*=\s*([^#\s][^#]*)") { return $Matches[1].Trim() }
    }
    return ''
}
$Docs = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Doublr'
Set-EnvValue 'DOUBLR_OUTPUT_DIR' $Docs
Set-EnvValue 'DOUBLR_DEVICE' $(if ($Gpu) { 'cuda' } else { 'cpu' })
Info "Vos fichiers doublés iront dans : $Docs"
Info 'Collez vos clés API (clic droit pour coller). Laissez vide pour passer : vous pourrez les saisir plus tard dans Réglages.'
$keys = [ordered]@{
    'ANTHROPIC_API_KEY'  = 'Clé Anthropic (traduction, console.anthropic.com)'
    'AZURE_SPEECH_KEY'   = 'Clé Azure Speech (voix, portal.azure.com)'
    'HF_TOKEN'           = 'Jeton Hugging Face (facultatif : plusieurs locuteurs)'
}
foreach ($k in $(if ($NonInteractive) { @() } else { $keys.Keys })) {
    $current = Get-EnvValue $k
    $label = $keys[$k]
    if ($current) { $label += ' [déjà renseignée, Entrée pour garder]' }
    $v = Read-Host "      $label"
    if ($v) { Set-EnvValue $k $v.Trim() }
}
if (-not $NonInteractive -and (Get-EnvValue 'AZURE_SPEECH_KEY')) {
    $region = Read-Host "      Région Azure [$(if (Get-EnvValue 'AZURE_SPEECH_REGION') { Get-EnvValue 'AZURE_SPEECH_REGION' } else { 'westeurope' })]"
    if ($region) { Set-EnvValue 'AZURE_SPEECH_REGION' $region.Trim() }
}

# --- 8. Raccourcis -------------------------------------------------------------------------
Step 8 'Raccourcis'
$Launcher = Join-Path $Root 'Doublr.bat'
@(
    '@echo off',
    'title Doublr',
    'set PYTHONUTF8=1',
    "cd /d `"$(Join-Path $App 'backend')`"",
    'echo.',
    'echo   Doublr demarre. Laissez cette fenetre ouverte pendant que vous utilisez Doublr.',
    'echo   Pour arreter Doublr, fermez cette fenetre.',
    'echo.',
    'start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep 6; Start-Process ''http://localhost:8000''"',
    "`"$VPy`" -m uvicorn app.main:app --host 127.0.0.1 --port 8000",
    'pause'
) | Set-Content -Path $Launcher -Encoding ASCII
$Updater = Join-Path $Root 'Mettre-a-jour-Doublr.bat'
@(
    '@echo off',
    'title Mise a jour de Doublr',
    "powershell -NoProfile -ExecutionPolicy Bypass -Command `"iex (irm 'https://raw.githubusercontent.com/$Repo/$Branch/installer/windows/install.ps1')`""
) | Set-Content -Path $Updater -Encoding ASCII

$Shell = New-Object -ComObject WScript.Shell
$StartMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Doublr'
New-Item -ItemType Directory -Force -Path $StartMenu | Out-Null
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), $StartMenu)) {
    $lnk = $Shell.CreateShortcut((Join-Path $dir 'Doublr.lnk'))
    $lnk.TargetPath = $Launcher
    $lnk.WorkingDirectory = $Root
    $lnk.IconLocation = "$env:SystemRoot\System32\SHELL32.dll,168"
    $lnk.Description = 'Doublage audio par IA'
    $lnk.Save()
}
$lnk = $Shell.CreateShortcut((Join-Path $StartMenu 'Mettre à jour Doublr.lnk'))
$lnk.TargetPath = $Updater
$lnk.Save()
Info 'Raccourci « Doublr » créé sur le Bureau et dans le menu Démarrer.'

Write-Host ''
Write-Host '  Installation terminée !' -ForegroundColor Cyan
Write-Host '  Double-cliquez sur « Doublr » sur votre Bureau : Doublr s''ouvrira dans votre navigateur.'
Write-Host ''
if (-not $NonInteractive) {
    $go = Read-Host '  Lancer Doublr maintenant ? (O/n)'
    if ($go -ne 'n' -and $go -ne 'N') { Start-Process -FilePath $Launcher }
}
