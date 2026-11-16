# Chelsy AI — create the PERMANENT Android release key (run once, on your own PC).
#
# Why: without a permanent key every CI build is signed by a new one-time key. Android then
# refuses to update over the previous install, and Google Play Protect sees a new unknown
# publisher every time and blocks or warns more often.
#
# Needs keytool (comes with Android Studio or any JDK 17+).
# The key never leaves your PC except as the GitHub secret you paste yourself.
#
#   powershell -ExecutionPolicy Bypass -File Android_Client\tools\new_release_key.ps1
#
# Output: chelsy-release.jks (KEEP A BACKUP — losing it means users must reinstall)
#         and the four values to paste into GitHub → Settings → Secrets and variables → Actions.

$ErrorActionPreference = 'Stop'
$keytool = (Get-Command keytool -ErrorAction SilentlyContinue).Source
if (-not $keytool) {
    $studio = "$env:ProgramFiles\Android\Android Studio\jbr\bin\keytool.exe"
    if (Test-Path $studio) { $keytool = $studio } else { throw 'keytool not found: install Android Studio or a JDK 17+.' }
}
$out = Join-Path (Get-Location) 'chelsy-release.jks'
if (Test-Path $out) { throw "$out already exists — keep using it, do not create a second key." }

$bytes = New-Object byte[] 24
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$password = -join ($bytes | ForEach-Object { $_.ToString('x2') })

& $keytool -genkeypair -keystore $out -alias chelsy-release -keyalg RSA -keysize 4096 -validity 10000 `
    -storepass $password -keypass $password -dname 'CN=Chelsy AI, O=Chelsy Group, C=RU'
if ($LASTEXITCODE -ne 0) { throw 'keytool failed' }

Write-Host ''
Write-Host 'Created' $out '— copy it to a safe place (password manager / encrypted backup).'
Write-Host ''
Write-Host 'Add these four repository secrets on GitHub (Settings -> Secrets and variables -> Actions):'
Write-Host '  ANDROID_KEYSTORE_BASE64 = (copied to clipboard now)'
Write-Host "  ANDROID_KEYSTORE_PASSWORD = $password"
Write-Host '  ANDROID_KEY_ALIAS = chelsy-release'
Write-Host "  ANDROID_KEY_PASSWORD = $password"
[Convert]::ToBase64String([IO.File]::ReadAllBytes($out)) | Set-Clipboard
Write-Host ''
Write-Host 'Certificate SHA-256 (needed for the Google developer verification / Play Protect appeal):'
& $keytool -list -v -keystore $out -storepass $password -alias chelsy-release | Select-String 'SHA256'
