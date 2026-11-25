"""'내보낸 폴더 열기'(명령 export.open_folder): 앱이 실제로 내보낸 자리만 탐색기로 연다. Qt를 import하지 않는다.

웹은 종류(kind)만 보내고 경로는 보내지 않는다. 폴더는 둘 가운데 하나다.
- excel·ie·fmea·dexpi: 이번 실행에서 이 프로젝트를 내보낼 때 저장 대화상자(engine.hooks의 save_path·save_dir)가 돌려준 자리(Hooks가 적어 둠).
  그 자리에 대화상자를 닫은 뒤 쓰인 파일(dexpi는 manifest.json)이 있을 때만 내보낸 것으로 본다.
- chat: 채팅 내보내기의 정해진 자리(작업 루트 output/exports).
UNC, 링크·접합을 지나는 자리, 없거나 폴더가 아닌 자리는 열지 않는다. 폴더만 여는 동작(explore)으로 열어 파일을 실행하지 않는다.
"""

import os
import time

from hazop import paths

KINDS = ("excel", "ie", "fmea", "dexpi", "chat")
DEXPI_FILE = "manifest.json"
SLACK = 2.0       # 파일 시각의 어림(초)
NOT_FOUND = "이번 실행에서 내보낸 폴더가 없습니다. 먼저 내보내세요."
REFUSED = "이 폴더는 열 수 없습니다. 탐색기에서 직접 여세요."


class Refused(Exception):
    pass


class Hooks(dict):
    """창이 꽂는 일의 표. 저장 대화상자가 돌려준 자리를 프로젝트·종류마다 적어 둔다(picked). 대화상자의 답은 바꾸지 않는다."""

    def __init__(self, project_fn):
        super().__init__()
        self.picked = {}          # (프로젝트, 종류) → [(쓸 파일, 대화상자를 닫은 시각)]
        self._project = project_fn

    def __setitem__(self, key, fn):
        if key == "save_path" and fn is not None:
            fn = self._noted(fn, lambda kind, path: path)
        elif key == "save_dir" and fn is not None:
            fn = self._noted(fn, lambda kind, path: os.path.join(path, DEXPI_FILE))
        super().__setitem__(key, fn)

    def _noted(self, fn, file_of):
        def run(kind, *args):
            path = fn(kind, *args)
            if path:
                self.picked.setdefault((self._project(), kind), []).append((file_of(kind, path), time.time()))
            return path
        return run


def _plain(folder):
    """링크·접합·UNC를 지나지 않는 폴더의 경로. 아니면 Refused."""
    full = os.path.abspath(folder)
    if full.startswith("\\\\") or os.path.normcase(os.path.realpath(full)) != os.path.normcase(full):
        raise Refused(REFUSED)
    if not os.path.isdir(full):
        raise Refused(NOT_FOUND)
    return full


def folder(engine, kind):
    """열 폴더. 없거나 열면 안 되면 Refused."""
    if kind == "chat":
        return _plain(paths.output_in(os.path.realpath(paths.work_root()), "exports"))
    for path, at in reversed(engine.hooks.picked.get((engine.project_id(), kind)) or []):
        if os.path.isfile(path) and os.path.getmtime(path) >= at - SLACK:
            return _plain(os.path.dirname(path))
    raise Refused(NOT_FOUND)


def open_folder(engine, kind):
    path = folder(engine, kind)
    explore = engine.hooks.get("explore") or (lambda p: os.startfile(p, "explore"))
    try:
        explore(path)
    except OSError as exc:
        raise Refused(REFUSED) from exc
    return path
