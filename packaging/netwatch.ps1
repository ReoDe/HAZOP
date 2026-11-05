# 패키징 W4: 대상 프로세스의 네트워크 연결 표본 조사(관찰만 함, 차단하지 않음).
# 사용: powershell -NoProfile -ExecutionPolicy Bypass -File packaging\netwatch.ps1 -Log <파일> [-Seconds 900]
#        [-PathLike "*\.hazop\venv-py312\*;*\Python312\python.exe"]   (프로세스 실행 파일 경로 와일드카드, ';' 구분)
# -PathLike는 문자열 하나로 받아 ';'로 나눈다(-File 호출은 배열 인자를 문자열 하나로 넘기기 때문).
# 멈추기: <Log>.stop 파일을 만들거나 -Seconds가 지나면 끝난다.
# 표본 줄: "sample <시각> dt_ms=<직전 표본과의 실제 간격> pids=<n> tcp_remote=<n> udp=<n>"
#   tcp_remote = 루프백·미지정 주소가 아닌 원격 주소의 TCP 연결 수. 세부 줄: "tcp ..." / "udp ..."
# 한계: 표본 사이의 짧은 연결은 놓칠 수 있다. 대상 경로에 맞지 않는 프로세스(예: 다른 자식 프로세스)는 보지 않는다.
param(
  [Parameter(Mandatory = $true)][string]$Log,
  [int]$Seconds = 900,
  [string]$PathLike = "*\.hazop\venv-py312\*;*\Python312\python.exe",
  [int]$IntervalMs = 1000
)
$patterns = @($PathLike -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$end = (Get-Date).AddSeconds($Seconds)
"start $(Get-Date -Format o) interval_ms=$IntervalMs patterns=$($patterns.Count) pathlike=$($patterns -join ';')" | Out-File -Encoding utf8 $Log
$prev = Get-Date
$n = 0
while ((Get-Date) -lt $end) {
  $now = Get-Date
  $dt = [int]($now - $prev).TotalMilliseconds
  $prev = $now
  $pids = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
      $p = $_.Path
      if ($p) { try { $p = [System.IO.Path]::GetFullPath($p) } catch { } }  # Qt가 보고하는 '\.\' 조각 제거
      $p -and ($patterns | Where-Object { $p -like $_ }) } | ForEach-Object { $_.Id })
  $tcp = @(); $udp = @()
  if ($pids.Count -gt 0) {
    $tcp = @(Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object {
        $pids -contains $_.OwningProcess -and $_.RemoteAddress -notin @('127.0.0.1', '::1', '0.0.0.0', '::') })
    $udp = @(Get-NetUDPEndpoint -ErrorAction SilentlyContinue | Where-Object { $pids -contains $_.OwningProcess })
  }
  $n++
  "sample $($now.ToString('o')) dt_ms=$dt pids=$($pids.Count) tcp_remote=$($tcp.Count) udp=$($udp.Count)" | Out-File -Append -Encoding utf8 $Log
  foreach ($c in $tcp) { "tcp pid=$($c.OwningProcess) $($c.RemoteAddress):$($c.RemotePort) $($c.State)" | Out-File -Append -Encoding utf8 $Log }
  foreach ($u in $udp) { "udp pid=$($u.OwningProcess) $($u.LocalAddress):$($u.LocalPort)" | Out-File -Append -Encoding utf8 $Log }
  if (Test-Path "$Log.stop") { break }
  Start-Sleep -Milliseconds $IntervalMs
}
"end $(Get-Date -Format o) samples=$n" | Out-File -Append -Encoding utf8 $Log
