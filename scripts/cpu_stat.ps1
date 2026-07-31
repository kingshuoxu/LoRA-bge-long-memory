$procs = @(Get-Process python -ErrorAction SilentlyContinue)
$cores = (Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors
"logical cores: $cores"
foreach ($p in $procs) {
    $ws = [math]::Round($p.WorkingSet64/1GB, 1)
    $line = 'PID {0}: threads {1}, RAM {2} GB, total CPU {3:N0}s' -f $p.Id, $p.Threads.Count, $ws, $p.CPU
    $line
}
if ($procs.Count -gt 0) {
    $p = $procs | Sort-Object WorkingSet64 -Descending | Select-Object -First 1
    $c1 = $p.CPU
    Start-Sleep -Seconds 2
    $p.Refresh()
    $c2 = $p.CPU
    $pct = ($c2 - $c1) / 2 / $cores * 100
    'PID {0} realtime CPU: {1:N1}% of machine' -f $p.Id, $pct
}
