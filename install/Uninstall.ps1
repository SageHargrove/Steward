# Removes the shortcuts Install.ps1 made. Nothing else exists to remove:
# nothing was copied, registered, or written outside your own Start Menu.
#
# Your data is untouched by this and by design. steward\data\steward.sqlite3
# is the activity history, which cannot be rebuilt from Discord, so no script
# in this project deletes it.

$ErrorActionPreference = 'Stop'

$FolderName = 'Server Setup for Discord'
$Programs = [Environment]::GetFolderPath('Programs')
$Desktop = [Environment]::GetFolderPath('Desktop')
$Dest = Join-Path $Programs $FolderName
$DesktopLink = Join-Path $Desktop 'Server Setup for Discord.lnk'

$removed = 0
if (Test-Path $Dest) {
    Remove-Item -Recurse -Force $Dest
    Write-Host "  Removed the Start Menu folder '$FolderName'." -ForegroundColor Green
    $removed++
}
if (Test-Path $DesktopLink) {
    Remove-Item -Force $DesktopLink
    Write-Host '  Removed the desktop shortcut.' -ForegroundColor Green
    $removed++
}

Write-Host ''
if ($removed -eq 0) {
    Write-Host '  There were no shortcuts to remove.'
} else {
    Write-Host '  Done. The program itself is untouched, and so is your ledger'
    Write-Host '  database. Run install\Install.bat to put the shortcuts back.'
}
Write-Host ''
