# Removes the shortcuts Install.ps1 made. Nothing else exists to remove:
# nothing was copied, registered, or written outside your own Start Menu.
#
# Your data is untouched by this and by design. steward\data\steward.sqlite3
# is the activity history, which cannot be rebuilt from Discord, so no script
# in this project deletes it.

$ErrorActionPreference = 'Stop'

# Every name this has shipped under, so an uninstall after a rename does not
# leave the old folder behind forever.
$Names = @('Steward', 'Server Setup for Discord', 'CommunityOps')
$Programs = [Environment]::GetFolderPath('Programs')
$Desktop = [Environment]::GetFolderPath('Desktop')

$removed = 0
foreach ($name in $Names) {
    $dest = Join-Path $Programs $name
    if (Test-Path $dest) {
        Remove-Item -Recurse -Force $dest
        Write-Host "  Removed the Start Menu folder '$name'." -ForegroundColor Green
        $removed++
    }
    $link = Join-Path $Desktop "$name.lnk"
    if (Test-Path $link) {
        Remove-Item -Force $link
        Write-Host "  Removed the '$name' desktop shortcut." -ForegroundColor Green
        $removed++
    }
}

Write-Host ''
if ($removed -eq 0) {
    Write-Host '  There were no shortcuts to remove.'
} else {
    Write-Host '  Done. The program itself is untouched, and so is your ledger'
    Write-Host '  database. Run install\Install.bat to put the shortcuts back.'
}
Write-Host ''
