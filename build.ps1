param(
    [string]$Python = 'python',
    [string]$OutputDirectory = ''
)

$ErrorActionPreference = 'Stop'

$SourcePath = Join-Path $PSScriptRoot 'task_floating_ball.py'
$IconPath = Join-Path $PSScriptRoot 'assets/app_icon.ico'
$VersionPath = Join-Path $PSScriptRoot 'version_info.txt'
$WorkPath = Join-Path $PSScriptRoot '.build/work'
$SpecPath = Join-Path $PSScriptRoot '.build'
$PythonExecutable = (Get-Command $Python -ErrorAction Stop).Source
$PythonDirectory = Split-Path -Parent $PythonExecutable
$OriginalPath = $env:PATH
$DistributionPath = $PSScriptRoot
if ($OutputDirectory) {
    $DistributionPath = if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
        $OutputDirectory
    } else {
        Join-Path $PSScriptRoot $OutputDirectory
    }
    $DistributionPath = [System.IO.Path]::GetFullPath($DistributionPath)
    New-Item -ItemType Directory -Path $DistributionPath -Force | Out-Null
}

try {
    # 只从 Python 和 Windows 解析依赖，避免其他工具的同名 DLL 混入包内。
    $env:PATH = (@(
        $PythonDirectory,
        (Join-Path $PythonDirectory 'DLLs'),
        (Join-Path $PythonDirectory 'Scripts'),
        (Join-Path $env:SystemRoot 'System32'),
        $env:SystemRoot
    ) | Select-Object -Unique) -join ';'

    & $PythonExecutable -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name '任务悬浮球' `
        --icon $IconPath `
        --version-file $VersionPath `
        --distpath $DistributionPath `
        --workpath $WorkPath `
        --specpath $SpecPath `
        $SourcePath

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 构建失败，退出码：$LASTEXITCODE"
    }
}
finally {
    $env:PATH = $OriginalPath
}
