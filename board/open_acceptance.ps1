#Requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet('menu','live','parallel','protocol','guide','verify','power')][string]$Action='menu',
    [string]$BaseUrl='http://169.254.135.99:9090',
    [string]$NotebookPath='uart_evidence/notebooks/uart_monitor.ipynb',
    [string]$RecordPath,
    [string]$PythonExe,
    [switch]$CheckOnly
)
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$repositoryLayout=Test-Path -LiteralPath (Join-Path $projectRoot 'src/pynq/scripts') -PathType Container
$pages=if($repositoryLayout){@{
    parallel='report/replays/binary_acceptance.html'
    protocol='report/replays/dual_protocol.html'
    guide='board/acceptance_computer_operations.md'
    power='board/pynq/README.md'
}}else{@{
    parallel='deliverables/URX2_新版八路与持续时间_实测_20261101.html'
    protocol='deliverables/URX2_同固件双协议验收_20261101.html'
    guide='deliverables/acceptance_computer_operations.md'
    power='docs/uart-monitor/power-retest-20261102.md'
}}
$verifyScript=Join-Path $projectRoot $(if($repositoryLayout){'board/verify_acceptance_export.py'}else{'scripts/verify_acceptance_export.py'})
function Get-NotebookUrl {
    $parsedUrl=$null
    if (-not [Uri]::TryCreate($BaseUrl,[UriKind]::Absolute,[ref]$parsedUrl) -or
        $parsedUrl.Scheme -notin @('http','https') -or $parsedUrl.UserInfo) {
        throw 'BaseUrl must be an HTTP/HTTPS address without embedded credentials.'
    }
    return $BaseUrl.TrimEnd('/')+'/notebooks/'+$NotebookPath.TrimStart('/')
}
function Open-AcceptanceItem([string]$Choice) {
    if ($Choice -eq 'live') {
        $url=Get-NotebookUrl
        Write-Host '正在打开板端 Notebook：' $url
        Write-Host '页面打开后仍需运行单元格、检查配置并开始监测。'
        Start-Process -FilePath $url
    } elseif ($Choice -eq 'verify') {
        $selectedRecord=$RecordPath
        if (-not $selectedRecord) { $selectedRecord=Read-Host '粘贴导出ZIP或会话目录的完整路径' }
        $selectedRecord=$selectedRecord.Trim().Trim('"').Trim("'")
        $selectedPython=$PythonExe
        if (-not $selectedPython) {
            $bundled=Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
            if (Test-Path -LiteralPath $bundled) {$selectedPython=$bundled}
            else {
                $command=Get-Command python.exe -ErrorAction SilentlyContinue
                if ($command -and $command.Source -notlike '*WindowsApps*') {$selectedPython=$command.Source}
                else {throw '未找到Python。请安装Python 3.8+，或用 -PythonExe 指定现有解释器。'}
            }
        }
        $env:PYTHONIOENCODING='utf-8'
        & $selectedPython $verifyScript --input $selectedRecord
        if ($LASTEXITCODE -ne 0) {throw '核验未通过，请保留上面的输出和verification.json。'}
    } else {
        $path=Join-Path $projectRoot $pages[$Choice]
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {throw "缺少文件：$path"}
        if ($Choice -in @('guide','power')) {Start-Process -FilePath notepad.exe -ArgumentList ('"'+$path+'"')}
        else {
            Write-Host '打开已保存实测记录；这是回放页面。'
            Start-Process -FilePath $path
        }
    }
}
if ($CheckOnly) {
    foreach($name in $pages.Values) {
        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $name) -PathType Leaf)) {throw "缺少文件：$name"}
    }
    if (-not (Test-Path -LiteralPath $verifyScript)) {throw '缺少核验脚本'}
    Write-Host 'Notebook目标：' (Get-NotebookUrl)
    Write-Host '入口文件检查通过；未打开页面，未连接板卡。'
    exit 0
}
if ($Action -ne 'menu') {Open-AcceptanceItem $Action;exit}
while ($true) {
    Write-Host ''
    Write-Host '验收电脑操作入口'
    Write-Host '1 打开PYNQ实时Notebook'
    Write-Host '2 打开八路并行实测回放'
    Write-Host '3 打开双协议实测回放'
    Write-Host '4 打开电脑操作说明'
    Write-Host '5 核验导出的ZIP或会话目录'
    Write-Host '6 查看固定IP与固件加载断电复测步骤'
    Write-Host '0 退出'
    $choice=Read-Host '输入编号后按回车'
    if ($choice -eq '0') {break}
    $mapping=@{'1'='live';'2'='parallel';'3'='protocol';'4'='guide';'5'='verify';'6'='power'}
    if (-not $mapping.ContainsKey($choice)) {Write-Host '请输入0到6。';continue}
    try {Open-AcceptanceItem $mapping[$choice]}
    catch {Write-Host $_.Exception.Message -ForegroundColor Red}
}
