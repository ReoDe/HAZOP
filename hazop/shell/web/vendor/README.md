# web/vendor — 묶음 라이브러리 (Preact, hooks, htm)

새 화면(`hazop-app://shell/…`)이 빌드 없이 읽는 ES 모듈이다. 받은 날 2026-11-13, 받은 곳은 npm 레지스트리(`registry.npmjs.org`)다. 받은 꾸러미의 스크립트는 실행하지 않았고 필요한 파일만 옮겼다(원본 풀어 둔 곳: `D:\HAZOP-trials\2026-11-13-web-vendor\`).

| 파일 | 출처 | 버전 | 라이선스 | 원본 SHA-256 | 이 폴더 파일 SHA-256 |
| --- | --- | --- | --- | --- | --- |
| `preact.module.js` | `preact/dist/preact.module.js` | preact 10.29.8 | MIT | `c30e721ebfdc6e2ad4c18c14d2dfb82667829c8aec27de1207774e3fc16858a8` | 같음(수정 없음) |
| `hooks.module.js` | `preact/hooks/dist/hooks.module.js` | preact 10.29.8 | MIT | `a6ee626f2d01570592dd569a792e3f050154aa02890eead8c223fa3ed5aa3d5a` | `f3555e7a8dba84175c94f17148ba6670e4b3716888fe06b3330a485637296a38`(아래 한 곳 수정) |
| `htm.module.js` | `htm/dist/htm.module.js` | htm 3.1.1 | **Apache-2.0** | `ab33dd3f38059b9be4d5f5350128eefb2356639c4e0bbe9d9e8b3ba75847e9e4` | 같음(수정 없음) |

- **받은 꾸러미.**
  - `https://registry.npmjs.org/preact/-/preact-10.29.8.tgz` — 407,547바이트, SHA-1 `fc85b82dc2474e245b1430b51781d417361f5fc3`(레지스트리 `dist.shasum`과 같음), SHA-256 `b18cb0a457f3d43c7bb30391a74ade7d13e03bc6e77915e061c70c0fe1123299`
  - `https://registry.npmjs.org/htm/-/htm-3.1.1.tgz` — 28,437바이트, SHA-1 `49266582be0dc66ed2235d5ea892307cc0c24b78`(같음), SHA-256 `2425b9bee11409177bcabc7f32e319926fc6690c1701c0b257c88bdff2d5ba90`
- **판을 고른 이유.** 규격(HZ-DSN-05 §5.1)이 Preact 10.x라 했다. 레지스트리의 최신은 11.2.0(2026-11-06)이지만 나온 지 일주일이라 10.x의 마지막 판 10.29.8을 쓴다. htm은 3.x의 최신 3.1.1이다.
- **수정 한 곳.** `hooks.module.js`의 첫 줄 `import{options as n}from"preact"`를 `from"./preact.module.js"`로 바꿨다. 맨 모듈 이름(`preact`)은 import 지도가 있어야 읽히는데, 이 화면은 CSP(`script-src hazop-app:`)로 인라인 스크립트를 막아 import 지도를 둘 수 없다. 이 한 곳 말고는 바이트가 같다.
- **라이선스.** `licenses/preact/LICENSE`(MIT), `licenses/htm/LICENSE`(Apache-2.0). 고지 목록은 `licenses/README.md`다. 규격 §5.1은 htm을 MIT라고 적었으나 실제 패키지의 `license`는 Apache-2.0이다(`package.json`과 LICENSE 원문 확인). 규격이 정한 허용 범위(MIT·ISC·Apache 2.0)에 든다.
- **소스맵.** 파일 끝의 `sourceMappingURL` 주석은 그대로 뒀다. 맵 파일은 두지 않으므로 개발자 도구가 열릴 때만 404가 난다.
- 줄 끝은 바꾸지 않는다(`.gitattributes`가 `hazop/shell/web/vendor/**`를 `-text`로 둔다).
