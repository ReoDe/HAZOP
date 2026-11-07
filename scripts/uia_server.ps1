# UI Automation helper for scripts/check_user_scenarios.py. Reads one JSON request per stdin line, writes one JSON line.
# Requests: {"op":"windows","pid":N} | {"op":"tree","pid":N,"cap":N} | {"op":"children","pid":N} | {"op":"focus"} | {"op":"quit"}
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$stdin = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), $utf8)
$stdout = New-Object System.IO.StreamWriter([Console]::OpenStandardOutput(), $utf8)
$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]

function Desc($e) {
    $c = $e.Current
    $r = $c.BoundingRectangle
    $rect = $null
    if (-not $r.IsEmpty) { $rect = @([int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height) }
    [ordered]@{ name = $c.Name; type = $c.ControlType.ProgrammaticName -replace '^ControlType\.', ''; aid = $c.AutomationId
        cls = $c.ClassName; rect = $rect; enabled = $c.IsEnabled; offscreen = $c.IsOffscreen; focus = $c.HasKeyboardFocus
        pid = $c.ProcessId; hwnd = $c.NativeWindowHandle; kbd = $c.IsKeyboardFocusable; value = (Value $e) }
}

function Value($e) {
    $vp = $null
    if ($e.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit -and
        $e.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$vp)) { return $vp.Current.Value }
    return $null
}

function Windows($procId) {
    $cond = New-Object System.Windows.Automation.PropertyCondition($AE::ProcessIdProperty, [int]$procId)
    return $AE::RootElement.FindAll($TS::Children, $cond)
}

while ($true) {
    $line = $stdin.ReadLine()
    if ($null -eq $line) { break }
    try {
        $q = $line | ConvertFrom-Json
        if ($q.op -eq 'quit') { break }
        $out = @()
        if ($q.op -eq 'windows') {
            foreach ($w in (Windows $q.pid)) { $out += ,(Desc $w) }
        } elseif ($q.op -eq 'tree') {
            $cap = if ($q.cap) { [int]$q.cap } else { 2000 }
            $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
            $stack = New-Object System.Collections.Stack
            $wins = @(Windows $q.pid)
            for ($i = $wins.Count - 1; $i -ge 0; $i--) { $stack.Push($wins[$i]) }
            while ($stack.Count -gt 0 -and $out.Count -lt $cap) {
                $e = $stack.Pop()
                try { $out += ,(Desc $e) } catch { continue }
                $kids = @()
                try {
                    $c = $walker.GetFirstChild($e)
                    while ($null -ne $c) { $kids += ,$c; $c = $walker.GetNextSibling($c) }
                } catch { }
                for ($i = $kids.Count - 1; $i -ge 0; $i--) { $stack.Push($kids[$i]) }
            }
        } elseif ($q.op -eq 'children') {
            foreach ($p in (Get-CimInstance Win32_Process -Filter "ParentProcessId=$([int]$q.pid)")) {
                $out += ,[ordered]@{ pid = [int]$p.ProcessId; name = $p.Name }
            }
        } elseif ($q.op -eq 'focus') {
            $f = $AE::FocusedElement
            if ($null -ne $f) { $out += ,(Desc $f) }
        } else { throw "unknown op $($q.op)" }
        $json = ConvertTo-Json -InputObject @{ ok = $true; items = $out } -Compress -Depth 4
    } catch {
        $json = ConvertTo-Json -InputObject @{ ok = $false; error = "$_" } -Compress
    }
    $stdout.WriteLine($json)
    $stdout.Flush()
}
