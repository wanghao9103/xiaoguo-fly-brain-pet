param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$Interpreter = (& $Python -c "from pathlib import Path; import sys; print(Path(sys.executable).with_name('pythonw.exe'))").Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Interpreter)) {
    throw 'Python with tkinter and pythonw is required.'
}
$DesktopDirectory = [Environment]::GetFolderPath('Desktop')
$AppPath = Join-Path $PSScriptRoot 'app.py'
$LinkPath = Join-Path $DesktopDirectory '小果 - 果蝇学习桌宠.lnk'
$ShellObject = New-Object -ComObject WScript.Shell
if (Test-Path -LiteralPath $LinkPath) {
    $ExistingLink = $ShellObject.CreateShortcut($LinkPath)
    if ($ExistingLink.TargetPath -ne $Interpreter -or $ExistingLink.Arguments -notlike ('*' + $AppPath + '*')) {
        throw 'A different shortcut with this name already exists; it was left unchanged.'
    }
}
$Shortcut = $ShellObject.CreateShortcut($LinkPath)
$Shortcut.TargetPath = $Interpreter
$Shortcut.Arguments = '"' + $AppPath + '"'
$Shortcut.WorkingDirectory = $PSScriptRoot
$Shortcut.Description = '小果：离线运行、可以学习行为偏好的桌面宠物'
$Shortcut.Save()
Write-Output $LinkPath
$LabAppPath = Join-Path $PSScriptRoot 'lab.py'
$LabLinkPath = Join-Path $DesktopDirectory '小果 - 学习实验室.lnk'
if (Test-Path -LiteralPath $LabLinkPath) {
    $ExistingLabLink = $ShellObject.CreateShortcut($LabLinkPath)
    if ($ExistingLabLink.TargetPath -ne $Interpreter -or $ExistingLabLink.Arguments -notlike ('*' + $LabAppPath + '*')) {
        throw 'A different laboratory shortcut exists; it was left unchanged.'
    }
}
$LabShortcut = $ShellObject.CreateShortcut($LabLinkPath)
$LabShortcut.TargetPath = $Interpreter
$LabShortcut.Arguments = '"' + $LabAppPath + '"'
$LabShortcut.WorkingDirectory = $PSScriptRoot
$LabShortcut.Description = '在独立副本中观察神经网络学习，打开本机实验室页面'
$LabShortcut.Save()
Write-Output $LabLinkPath
