# Creates the Outreach Studio shortcuts (Desktop and Start Menu).
# Safe to run again any time. Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File scripts\install_shortcuts.ps1

$project = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $project "Start Outreach.bat"
$icon = Join-Path $project "assets\outreach_studio.ico"

# Remove any old-brand shortcuts so only the new name remains.
$oldNames = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "DigiDental Outreach.lnk"),
    (Join-Path ([Environment]::GetFolderPath('StartMenu')) "Programs\DigiDental Outreach.lnk")
)
foreach ($old in $oldNames) {
    if (Test-Path $old) { Remove-Item $old -Force }
}

$shell = New-Object -ComObject WScript.Shell
$locations = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "Outreach Studio.lnk"),
    (Join-Path ([Environment]::GetFolderPath('StartMenu')) "Programs\Outreach Studio.lnk")
)

foreach ($path in $locations) {
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $launcher
    $shortcut.WorkingDirectory = $project
    $shortcut.Description = "Open Outreach Studio"
    if (Test-Path $icon) { $shortcut.IconLocation = "$icon,0" }
    $shortcut.Save()
    Write-Output "Created: $path"
}

Write-Output ""
Write-Output "To pin it: press the Windows key, type Outreach Studio,"
Write-Output "right-click the result, and choose Pin to Start."
