# Puts this on the Start Menu.
#
# Per-user on purpose: everything goes under the current account's own Start
# Menu folder, so it needs no administrator rights and touches nothing outside
# your profile. Nothing is copied, nothing is registered, no services. The
# shortcuts point at the files where they already sit, so `git pull` updates
# what the Start Menu launches without reinstalling anything.
#
# Undo it with Uninstall.ps1, or by deleting the folder it names at the end.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Icon = Join-Path $Root 'brand\steward.ico'
$FolderName = 'Steward'

function New-Shortcut {
    param($Path, $Target, $WorkDir, $Description)
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = $Target
    $link.WorkingDirectory = $WorkDir
    $link.Description = $Description
    if (Test-Path $Icon) { $link.IconLocation = "$Icon,0" }
    $link.Save()
    [Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null
}

Write-Host ''
Write-Host '  Steward' -ForegroundColor White
Write-Host '  -------'
Write-Host ''

# Refuse rather than make shortcuts that point at nothing. A dead Start Menu
# entry is worse than no Start Menu entry: it fails silently months later.
$required = @(
    (Join-Path $Root 'START.bat'),
    (Join-Path $Root 'ui\app.py'),
    (Join-Path $Root 'steward\bot.py')
)
foreach ($f in $required) {
    if (-not (Test-Path $f)) {
        Write-Host "  Cannot find $f" -ForegroundColor Red
        Write-Host '  Run this from inside the CommunityOps folder it came in.'
        Write-Host ''
        exit 1
    }
}

if (-not (Test-Path $Icon)) {
    Write-Host '  No icon at brand\steward.ico, so the shortcuts will use the'
    Write-Host '  default one. Regenerate it with: python brand\icon.py'
    Write-Host ''
}

$Programs = [Environment]::GetFolderPath('Programs')
$Dest = Join-Path $Programs $FolderName
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

New-Shortcut -Path (Join-Path $Dest 'Steward.lnk') `
    -Target (Join-Path $Root 'START.bat') -WorkDir $Root `
    -Description 'Set up and run your Discord community server'

New-Shortcut -Path (Join-Path $Dest 'Steward ledger only.lnk') `
    -Target (Join-Path $Root 'steward\START-LEDGER.bat') `
    -WorkDir (Join-Path $Root 'steward') `
    -Description 'Run just the bot, without the setup page'

New-Shortcut -Path (Join-Path $Dest 'Remove these shortcuts.lnk') `
    -Target (Join-Path $Root 'install\Uninstall.bat') `
    -WorkDir $Root -Description 'Delete the Start Menu and desktop shortcuts'

Write-Host "  Added to the Start Menu under '$FolderName'." -ForegroundColor Green

# The desktop one is opt-in. Plenty of people keep a clean desktop and a
# shortcut they did not ask for is a small rudeness.
$answer = Read-Host '  Put a shortcut on the desktop as well? (y/N)'
if ($answer -match '^(y|yes)$') {
    $desktop = [Environment]::GetFolderPath('Desktop')
    New-Shortcut -Path (Join-Path $desktop 'Steward.lnk') `
        -Target (Join-Path $Root 'START.bat') -WorkDir $Root `
        -Description 'Set up and run your Discord community server'
    Write-Host '  Added to the desktop.' -ForegroundColor Green
}

Write-Host ''
Write-Host '  Press the Windows key and start typing "Steward".'
Write-Host ''
Write-Host '  Nothing was copied or registered. The shortcuts point at this'
Write-Host "  folder ($Root), so updating the files updates what they launch."
Write-Host ''
