// 스캔 도면 알림줄: 스캔으로 읽은 도면은 자동으로 읽은 결과가 적고 미확인이 많다는 것을 도면 위에 한 줄로 알린다(A19, 조사 세션 요청).
// 스캔 여부와 해상도는 읽기 `scan/<graph_id>`가 준다(추출 결과 source.format·run.settings.scale.dpi). 도면마다 한 번 닫을 수 있다.
import { html } from "./ui/html.js";
import { useEffect, useState } from "../vendor/hooks.module.js";
import { read } from "./bridge.js";
import { Icon } from "./ui/icon.js";
import { Btn } from "./ui/parts.js";

export function scanText(scan) {
  return "스캔 도면" + (scan.dpi ? " · " + scan.dpi + " dpi" : "") + " · 자동으로 읽은 결과가 적고 미확인이 많습니다. AI 검토를 켜면 후보를 더 받을 수 있습니다.";
}

export function ScanNote({ sheet }) {
  const [scan, setScan] = useState(null);
  const [closed, setClosed] = useState({});
  useEffect(() => {
    let live = true;
    setScan(null);
    if (sheet) read("scan/" + encodeURIComponent(sheet)).then((d) => { if (live) setScan(d && d.scan ? d.scan : null); }).catch(() => { if (live) setScan(null); });
    return () => { live = false; };
  }, [sheet]);
  if (!scan || closed[sheet]) return null;
  return html`<div class="float scan-note" role="note" aria-label="스캔 도면 알림"><${Icon} name="alert-triangle" size=${16} />
    <div><div>${scanText(scan)}</div>${scan.low_resolution ? html`<div class="muted small">${scan.low_resolution}</div>` : null}</div>
    <${Btn} sm=${true} kind="ghost" icon="x" label="스캔 알림 닫기" onClick=${() => setClosed(Object.assign({}, closed, { [sheet]: true }))} /></div>`;
}
