# VanGuard demo launcher — one command from cold to filmable.
#
#   .\scripts\demo.ps1                          # sunny_midday hero shot
#   .\scripts\demo.ps1 -Scenario dusk_low       # the cooktop question take
#   .\scripts\demo.ps1 -Stop                    # tear everything down
#
# What it does: seeds history so sparklines are full from frame one, starts
# the poller (warmed into the same day), starts the API, pre-warms the model
# so the first on-camera question doesn't sit through a compile, then opens
# the dashboard. Scenario presets are seeded — a re-shoot gets the same
# numbers (PLAN.md §7).

param(
    [ValidateSet("sunny_midday", "dusk_low", "overnight_drain", "shore_power", "cloudy_marginal", "road_trip", "driveway")]
    [string]$Scenario = "sunny_midday",
    [double]$SeedHours = 0,      # 0 = auto per scenario
    [int]$Port = 8000,
    [switch]$Stop,
    [switch]$NoBrowser
)

$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo ".venv\Scripts\python.exe"
$demoDir = Join-Path $repo "sim\captures\demo"
$pidFile = Join-Path $demoDir "pids.txt"

if ($Stop) {
    if (Test-Path $pidFile) {
        Get-Content $pidFile | ForEach-Object {
            try { Stop-Process -Id ([int]$_) -Force -ErrorAction Stop; Write-Host "stopped $_" }
            catch { Write-Host "already gone: $_" }
        }
        Remove-Item $pidFile
    } else { Write-Host "nothing to stop" }
    exit 0
}

if ($SeedHours -le 0) {
    # Enough history for a full sparkline without contradicting the preset's
    # story: a full day for daytime scenes, the evening so far for dusk ones.
    $SeedHours = switch ($Scenario) {
        "dusk_low"        { 2 }
        "overnight_drain" { 3 }
        "shore_power"     { 4 }
        "road_trip"       { 0.25 }   # still mid-route on the Pacific Rim Hwy
        default           { 24 }
    }
}

New-Item -ItemType Directory -Force $demoDir | Out-Null
$db = Join-Path $demoDir "demo_$Scenario.db"
foreach ($suffix in "", "-wal", "-shm") {
    if (Test-Path "$db$suffix") { Remove-Item "$db$suffix" -Force }
}

Write-Host "== seeding $SeedHours h of $Scenario =="
& $py (Join-Path $repo "scripts\seed_db.py") $db $Scenario $SeedHours
if ($LASTEXITCODE -ne 0) { Write-Error "seeding failed"; exit 1 }

$cfg = Join-Path $demoDir "devices_$Scenario.yaml"
$dbYaml = ($db -replace '\\', '/')
@"
source: sim
poll_interval_s: 5
db_path: $dbYaml
sim:
  scenario: $Scenario
  speed: 1.0
  warmup_h: $SeedHours
inference:
  model_dir: ov_qwen3_4b_instruct_2507_int4_npu
  device_order: [GPU, NPU, CPU]
"@ | Out-File -Encoding utf8 $cfg

Write-Host "== starting poller + api (port $Port) =="
$env:VANGUARD_CONFIG = $cfg
$poller = Start-Process -FilePath $py -ArgumentList "-m", "poller", "--config", $cfg `
    -WorkingDirectory $repo -WindowStyle Hidden -PassThru
$api = Start-Process -FilePath $py -ArgumentList "-m", "uvicorn", "api.main:app", "--port", "$Port" `
    -WorkingDirectory $repo -WindowStyle Hidden -PassThru
"$($poller.Id)`n$($api.Id)" | Out-File $pidFile

Write-Host "== waiting for API =="
$deadline = (Get-Date).AddSeconds(60)
do {
    Start-Sleep -Milliseconds 500
    try { $ok = (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/status" -TimeoutSec 2).StatusCode -eq 200 }
    catch { $ok = $false }
} until ($ok -or (Get-Date) -gt $deadline)
if (-not $ok) { Write-Error "API did not come up"; exit 1 }

Write-Host "== pre-warming the model (first load takes ~15s GPU / ~90s NPU) =="
try {
    $body = '{"messages":[{"role":"user","content":"one-word health check"}],"max_tokens":8}'
    Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/chat/completions" -Method Post `
        -ContentType "application/json" -Body $body -TimeoutSec 300 | Out-Null
    Write-Host "model warm."
} catch {
    Write-Warning "pre-warm failed (model not exported?): $_"
}

Write-Host ""
Write-Host "READY  →  http://127.0.0.1:$Port   scenario=$Scenario (SIM badge on, as it must be)"
Write-Host "Stop with:  .\scripts\demo.ps1 -Stop"
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
