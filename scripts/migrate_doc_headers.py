"""문서 머리(HZ-GOV-02 §4.7)와 결정로그 고정 번호 열(§4.8)을 넣는다. 이름 이전 단계 3에서 쓴다.

    python scripts/migrate_doc_headers.py            바뀔 문서를 보여 준다(쓰지 않음)
    python scripts/migrate_doc_headers.py --apply    쓴다

머리가 이미 있는 문서와 번호 열이 이미 있는 결정로그는 건드리지 않으므로 다시 돌려도 결과가 같다.
결정 번호는 번호를 매기는 날의 파일 줄 번호다. 옛 문서가 적은 '결정로그 n행'이 그대로 DEC-n이 된다.
머리를 달면 줄 번호가 밀리므로 결정로그는 번호부터 넣고 머리를 단다.
"""

import argparse
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from tests import test_naming_rules as rules  # noqa: E402

# 문서번호(HZ-GOV-02 §5.2). 한 번 준 번호는 바꾸지 않는다.
DOC_IDS = {
    "specs/overview.md": "HZ-PLN-01",
    "specs/integration.md": "HZ-PLN-02",
    "specs/registration.md": "HZ-PLN-03",
    "specs/extraction.md": "HZ-PLN-04",
    "specs/hazop-analysis.md": "HZ-PLN-05",
    "specs/review-results.md": "HZ-PLN-06",
    "specs/hazop-method-guide.md": "HZ-PLN-07",
    "specs/graph-survey.md": "HZ-PLN-08",
    "specs/graph-usage.md": "HZ-PLN-09",
    "specs/interface.md": "HZ-PLN-10",
    "specs/stage-chain-check.md": "HZ-PLN-11",
    "specs/criteria-comparison.md": "HZ-PLN-12",
    "specs/kg-schema.md": "HZ-PLN-13",
    "specs/kg-schema-dictionary.md": "HZ-PLN-14",
    "specs/kg-schema-input.md": "HZ-PLN-15",
    "specs/ie-hazop-survey.md": "HZ-PLN-16",
    "specs/ie-output-design.md": "HZ-PLN-17",
    "specs/ai-subscription.md": "HZ-PLN-18",
    "specs/pid-symbol-dictionary.md": "HZ-PLN-19",
    "specs/study-node-segmentation.md": "HZ-PLN-20",
    "specs/flows/00-overview.md": "HZ-FLW-00",
    "specs/flows/01-registration.md": "HZ-FLW-01",
    "specs/flows/02-extraction.md": "HZ-FLW-02",
    "specs/flows/03-integration.md": "HZ-FLW-03",
    "specs/flows/04-hazop-analysis.md": "HZ-FLW-04",
    "specs/flows/05-review-results.md": "HZ-FLW-05",
    "design/output-screen-ax-demo.md": "HZ-DSN-01",
    "design/kg-screen.md": "HZ-DSN-02",
    "design/screen-spec.md": "HZ-DSN-03",
    "design/ai-connection-screens.md": "HZ-DSN-04",
    "methodology/combined-risk-methods.md": "HZ-MTH-01",
    "records/README.md": "HZ-REC-01",
    "records/decision-log.md": "HZ-REC-02",
    "records/backlog.md": "HZ-REC-03",
    "packaging/other-pc-checklist.md": "HZ-CHK-01",
}
DECISION_LOG = "records/decision-log.md"
HEADER = "---\ndoc_id: %s\nrev: 0\nstatus: review\nauthor: unknown\nreviewed: —\napproved: —\n---\n\n"
NUMBER_HEAD, NUMBER_RULE = "| 번호 ", "| --- "
DEC_PREFIX = re.compile(r"\| DEC-\d{4} ")
RULE_ROW = re.compile(r"\|(\s*:?-+:?\s*\|)+\s*\Z")


class HeaderError(Exception):
    pass


def add_header(text, doc_id):
    if rules.front_matter(text) is not None:
        return text
    bom = "﻿" if text.startswith("﻿") else ""
    newline = "\r\n" if "\r\n" in text else "\n"
    return bom + (HEADER % doc_id).replace("\n", newline) + text[len(bom):]


def add_decision_ids(text):
    """표의 첫 열로 번호를 넣는다. 제목 줄과 구분 줄 다음의 표 줄마다 `DEC-<그 줄의 줄 번호>`."""
    lines = text.splitlines(keepends=True)
    if any(line.startswith(NUMBER_HEAD) for line in lines):
        return text
    if rules.front_matter(text) is not None:
        raise HeaderError("머리를 단 뒤에는 줄 번호가 밀려서 결정 번호를 매길 수 없다")
    table = [no for no, line in enumerate(lines) if line.startswith("|")]
    if len(table) < 2 or not RULE_ROW.match(lines[table[1]].strip()):
        raise HeaderError("결정로그 표의 제목 줄과 구분 줄을 찾지 못했다")
    prefix = {table[0]: NUMBER_HEAD, table[1]: NUMBER_RULE}
    for no in table[2:]:
        prefix[no] = "| DEC-%04d " % (no + 1)
    return "".join(prefix.get(no, "") + line for no, line in enumerate(lines))


def strip_decision_ids(text):
    """add_decision_ids가 넣은 열만 뺀다. 넣기 전 글과 같은지 대조할 때 쓴다."""
    out = []
    for line in text.splitlines(keepends=True):
        for head in (NUMBER_HEAD, NUMBER_RULE):
            if line.startswith(head):
                line = line[len(head):]
                break
        else:
            m = DEC_PREFIX.match(line)
            line = line[m.end():] if m else line
        out.append(line)
    return "".join(out)


def planned(repo=REPO_ROOT):
    """(경로, 지금 글, 바뀐 글)을 바뀌는 문서만 낸다."""
    out = []
    for path, doc_id in DOC_IDS.items():
        full = os.path.join(repo, path)
        if not os.path.isfile(full):
            raise HeaderError("문서가 없다: %s" % path)
        with open(full, encoding="utf-8", newline="") as f:
            old = f.read()
        new = add_decision_ids(old) if path == DECISION_LOG else old
        new = add_header(new, doc_id)
        if new != old:
            out.append((path, old, new))
    return out


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="문서를 고쳐 쓴다")
    ap.add_argument("--repo", default=REPO_ROOT)
    args = ap.parse_args(argv)
    try:
        changes = planned(args.repo)
    except HeaderError as e:
        print("멈춤: %s" % e, file=sys.stderr)
        return 2
    for path, _old, new in changes:
        if args.apply:
            with open(os.path.join(args.repo, path), "w", encoding="utf-8", newline="") as f:
                f.write(new)
        print("%s: %s" % ("머리를 달았다" if args.apply else "머리를 달 문서", path))
    print("%s %d개 (대상 %d개)" % ("고친 문서" if args.apply else "고칠 문서", len(changes), len(DOC_IDS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
