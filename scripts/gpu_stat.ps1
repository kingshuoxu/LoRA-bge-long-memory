$s = (Get-Counter '\GPU Process Memory(*)\Local Usage' -ErrorAction SilentlyContinue).CounterSamples | Where-Object { $_.CookedValue -gt 100MB } | Sort-Object CookedValue -Descending | Select-Object -First 5
$s | ForEach-Object { '{0}: {1:N2} GB' -f $_.InstanceName, ($_.CookedValue/1GB) }
'---'
$u = (Get-Counter '\GPU Engine(*compute*)\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples | Where-Object { $_.CookedValue -gt 1 } | Sort-Object CookedValue -Descending | Select-Object -First 3
$u | ForEach-Object { '{0}: {1:N0}%' -f $_.InstanceName, $_.CookedValue }
