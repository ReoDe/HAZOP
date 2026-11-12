"""추출 실행 정보(extraction_run.json): 추출 결과 폴더에 추출 단계가 남기는 곁 파일(기획서 specs/pid-symbol-dictionary.md D8).

이 추출 결과가 어느 기호 사전 판으로 나왔는지 되짚는 데 쓴다. 그래프는 extraction.json만 읽으므로 이 파일은
graph_version에 들어가지 않는다. 사전 판을 extraction.json에 넣으면 사전 항목 하나만 고쳐도 거의 모든 PDF 도면의 판이
바뀌기 때문에 따로 둔다. 추출하지 못한 쪽(not_extracted.json)에도 남기고, 같은 자료를 다시 추출하면 그 실행의 값으로
덮어쓴다. 사람이 고치는 파일이 아니다. 이 파일이 없는 폴더(이 기록을 두기 전의 추출 결과)는 그대로 읽힌다.

    {"schema_version": "1", "extractor": "pdf_vector", "extracted": true,
     "extraction_run_id": "extract-pdf-…", "written_at": "2026-11-11T01:02:03Z",
     "symbol_dictionary_versions": {"APR1400": "2c997ba7e6ce", "공통": "ac25f22101ce"}}

extracted가 false면 extraction_run_id는 null이다. 기호 사전을 쓰지 않는 추출기(drawio)는 symbol_dictionary_versions가 null이다.

이 파일은 기록일 뿐이다. 추출 단계는 record()로 쓰고, 쓰지 못해도 추출 결과를 그대로 둔다.
"""

import logging
import os

from hazop import store_io

FILE_NAME = "extraction_run.json"
SCHEMA_VERSION = "1"
_log = logging.getLogger(__name__)


def write(out_dir, extractor, result=None, symbol_versions=None):
    """out_dir에 실행 정보를 쓴다(원자적, 있으면 덮어씀). result: 추출 결과 dict(추출하지 못했으면 None).
    symbol_versions: 이 실행이 읽은 기호 사전의 묶음별 판(symbols.Library.versions). 사전을 쓰지 않는 추출기는 None."""
    doc = {"schema_version": SCHEMA_VERSION, "extractor": extractor, "extracted": result is not None,
           "extraction_run_id": result["extraction_run_id"] if result is not None else None,
           "written_at": store_io.now_utc(),
           "symbol_dictionary_versions": dict(symbol_versions) if symbol_versions is not None else None}
    store_io.write_json(os.path.join(out_dir, FILE_NAME), doc)
    return doc


def record(out_dir, extractor, result=None, symbol_versions=None, warnings=None):
    """write와 같되 파일을 쓰지 못해도(OSError) 멈추지 않는다. 그때는 경고를 로그에 남기고 warnings(list)에 더한 뒤
    None을 돌려준다. 전에 쓴 파일은 지금 추출 결과의 기록처럼 읽히지 않게 지운다. 지우지도 못하면 경고에 적는다
    (남은 파일의 extraction_run_id가 지금 추출 결과와 다르다)."""
    try:
        return write(out_dir, extractor, result, symbol_versions)
    except OSError as exc:
        path = os.path.join(out_dir, FILE_NAME)
        text = "경고: 추출 실행 정보(%s)를 쓰지 못함: %s. 추출 결과는 그대로 둔다" % (path, exc)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            text += ". 지난 실행의 기록이 그 파일에 남아 있다"
        _log.warning(text)
        if warnings is not None:
            warnings.append(text)
        return None

