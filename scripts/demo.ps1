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
#
# The shoot (VanGuard_Scripts_ShotList.docx) launches with a take profile:
#   .\scripts\demo.ps1 -Scenario driveway -NPU -Presentation -Kiosk -Take forgot_switch
# A take scripts the demo drive's event schedule against the Drive press:
# 20% crossing +20s (fast variant +12s), Guardian Stage 1 (Starlink) +28s,
# Stage 2 (rear A/C) +40s, why-chip after the final stage. Park resets the
# take completely; consecutive takes reproduce within ~1s.

param(
    [ValidateSet("sunny_midday", "dusk_low", "overnight_drain", "shore_power", "cloudy_marginal", "road_trip", "driveway", "overnight_guardian", "charging_path_fault", "arrival_cleanup")]
    [string]$Scenario = "sunny_midday",
    [ValidateSet("", "forgot_switch", "forgot_switch_fast")]
    [string]$Take = "",          # filmed-take event schedule (see above)
    [double]$SeedHours = 0,      # 0 = auto per scenario
    [int]$Port = 8000,
    [switch]$Stop,
    [switch]$NoBrowser,
    [switch]$Kiosk,              # open Edge in fullscreen kiosk (no chrome;
                                 # close with Alt+F4)
    [switch]$NPU,                # serve the LLM on the NPU (real; ~90s compile)
    [switch]$Presentation        # filming mode: hides SIM labels in the UI.
                                 # Data-layer stamps stay; see BUILD_LOG.
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

if ($SeedHours -le 0 -and $Take) {
    # A take pins SOC at its mark until the Drive press; a short seed keeps
    # the flat battery line honest-looking (the story starts at the press).
    $SeedHours = 2
}
if ($SeedHours -le 0) {
    # Enough history for a full sparkline without contradicting the preset's
    # story: a full day for daytime scenes, the evening so far for dusk ones.
    $SeedHours = switch ($Scenario) {
        "dusk_low"        { 2 }
        "overnight_drain" { 3 }
        "shore_power"     { 4 }
        "road_trip"       { 0.25 }   # still mid-route on the Pacific Rim Hwy
        "overnight_guardian" { 1 }   # 31% just after midnight, drain running
        "charging_path_fault" { 0.25 } # mid-drive, engine fine, house starved
        "arrival_cleanup"    { 0.5 }  # route parks at ~36 min → arrives ~6
                                      # minutes into the live session
        default           { 24 }
    }
}

New-Item -ItemType Directory -Force $demoDir | Out-Null
$db = Join-Path $demoDir "demo_$Scenario.db"
foreach ($suffix in "", "-wal", "-shm") {
    # A just-stopped process can hold the db for a moment — retry briefly.
    for ($try = 0; $try -lt 10; $try++) {
        if (-not (Test-Path "$db$suffix")) { break }
        try { Remove-Item "$db$suffix" -Force -ErrorAction Stop; break }
        catch { Start-Sleep -Milliseconds 500 }
    }
}

Write-Host "== seeding $SeedHours h of $Scenario$(if ($Take) { ", take $Take" }) =="
$seedArgs = @((Join-Path $repo "scripts\seed_db.py"), $db, $Scenario, $SeedHours)
if ($Take) { $seedArgs += $Take }
& $py @seedArgs
if ($LASTEXITCODE -ne 0) { Write-Error "seeding failed"; exit 1 }

$cfg = Join-Path $demoDir "devices_$Scenario.yaml"
$dbYaml = ($db -replace '\\', '/')
$order = if ($NPU) { "[NPU, GPU, CPU]" } else { "[GPU, NPU, CPU]" }
$pres = if ($Presentation) { "true" } else { "false" }
if ($Take) {
    # Take mode: 1s poll + 1s guardian so the shot-list clock lands within
    # ~1s across takes; the detector set narrowed so nothing talks over the
    # battery-saver story; alerts tuned so the 20% crossing is THE alert.
    $takeLines = @"
  take: $Take
"@
    $pollInterval = 1
    $guardianBlock = @"
guardian:
  interval_s: 1
  default_level: protect
  # No arrival detector during a take: Park is the reset button between
  # takes, and arrival-cleanup would re-shed the dish the reset restores.
  detectors: [sag, battery_saver]
alerts:
  soc_warn_pct: 20.0
  tte_warn_h: 0.5
  alt_missing_severity: advisory
  reserve_warning: false
"@
} else {
    $takeLines = ""
    $pollInterval = 2
    $guardianBlock = @"
guardian:
  interval_s: 15
  default_level: protect
"@
}
@"
source: sim
poll_interval_s: $pollInterval
db_path: $dbYaml
presentation: $pres
sim:
  scenario: $Scenario
  speed: 1.0
  warmup_h: $SeedHours
$takeLines
inference:
  model_dir: ov_qwen3_4b_instruct_2507_int4_npu
  device_order: $order
watchdog:
  interval_min: 5
  use_model: true
$guardianBlock
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

if ($Presentation -and -not $Take) {
    # Filming default: bring the Starlink uplink online for the shot.
    # (A take arms the dish itself, already warm — no command needed.)
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/network" -Method Post `
            -ContentType "application/json" -Body '{"mode":"starlink"}' | Out-Null
        Write-Host "presentation mode: SIM labels hidden, Starlink coming online (~45s dish boot)."
    } catch {}
}

Write-Host ""
Write-Host "READY  →  http://127.0.0.1:$Port   scenario=$Scenario$(if ($Take) { "  take=$Take (event clock armed at the Drive press)" }) (SIM badge on, as it must be)"
Write-Host "Stop with:  .\scripts\demo.ps1 -Stop"
if ($Kiosk) {
    $edge = @("C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              "C:\Program Files\Microsoft\Edge\Application\msedge.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($edge) {
        Start-Process $edge -ArgumentList "--new-window", "--kiosk",
            "http://127.0.0.1:$Port", "--edge-kiosk-type=fullscreen"
        Write-Host "kiosk mode: Alt+F4 to exit."
    } else { Start-Process "http://127.0.0.1:$Port" }
} elseif (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
