param(
    [ValidateSet('software','sim','build','all')][string]$Stage='software',
    [string]$PythonExe='python',
    [string]$VivadoPath='vivado',
    [ValidatePattern('^[A-Za-z0-9_]+$')][string]$Label=('run_'+[DateTime]::Now.ToString('yyyyMMdd_HHmmss'))
)
$ErrorActionPreference='Stop'
if($PSVersionTable.PSVersion.Major -lt 7){throw 'Use PowerShell 7.'}
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    New-Item -ItemType Directory -Force build/uart_detector2 | Out-Null
    function Check-Python([string[]]$Arguments) {
        & $PythonExe @Arguments
        if($LASTEXITCODE -ne 0){throw 'URX2 Python verification failed'}
    }
    function Run-Vivado([string]$Script,[string]$RunLabel,[string]$Name,[string]$Marker) {
        $log="build/uart_detector2/${Label}_${Name}.log"
        & $VivadoPath -mode batch -nojournal -nolog -source $Script -tclargs $RunLabel *> $log
        $code=$LASTEXITCODE
        Get-Content -LiteralPath $log -Tail 5
        if($code -ne 0 -or !(Select-String -LiteralPath $log -Pattern "^$Marker`r?$" -Quiet)){throw "URX2 $Name failed; inspect $log"}
    }
    if($Stage -in @('software','all')) {
        Check-Python -Arguments @('-m','unittest','discover','-s','tests','-p','test_uart_*.py','-v')
    }
    if($Stage -in @('sim','all')) {
        Check-Python -Arguments @('scripts/generate_urx2_vectors.py')
        Run-Vivado scripts/simulate_urx2.tcl $Label core URX2_ALL_DETECTOR_SIMULATIONS_PASS
        Check-Python -Arguments @('scripts/verify_urx2_simulation.py','--attempt',"build/uart_detector2/simulation/$Label")
        Check-Python -Arguments @('scripts/check_urx2_wave.py',"build/uart_detector2/simulation/$Label/parallel8.vcd")
        Run-Vivado scripts/simulate_urx2_axi.tcl $Label axi URX2_AXI_SIMULATION_PASS
        Check-Python -Arguments @('scripts/verify_urx2_pipeline.py','--attempt',"build/uart_detector2/simulation/$Label",'--output',"build/uart_detector2/pipeline_$Label")
    }
    if($Stage -in @('build','all')) {
        Run-Vivado scripts/build_urx2.tcl $Label implementation URX2_BUILD_PASS
        Run-Vivado scripts/inspect_urx2_release.tcl $Label lanes URX2_EIGHT_PHYSICAL_RULE_LANES_VERIFIED
    }
} finally {Pop-Location}
