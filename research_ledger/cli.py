"""명령줄 실행: python -m research_ledger <명령> ...

  search   "검색어"            실재 문헌을 Crossref·OpenAlex·(KCI) 에서 찾아 후보 출력, --add 로 대장에 추가
  import   보고서.pdf           보고서의 참고문헌 목록을 읽어 대장에 등록(이미 있는 번호는 건너뜀)
  verify                       대장 문헌의 실재 여부를 자동 확인(--ref 14 로 한 건만, --force 로 재확인)
  check    보고서.pdf           본문 인용과 대장을 대조해 점검 결과(마크다운) 작성
  export                       대장을 엑셀(자료 대장·인용 대조·요약 시트)로 내보내기
  set      14 url=... exist_status=확인   수동 확인 결과 기록
  summary                      대장 현황 출력
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import crosscheck as cc
from . import refparse, verify
from .ledger import Ledger
from .models import EXIST_CONFIRMED, EXIST_STATUSES, SOURCE_FIELDS, Source

DEFAULT_DIR = "data/ledger"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="research_ledger", description="선행연구 수집·자료 검토 대장")
    p.add_argument("--ledger", default=DEFAULT_DIR, help="대장 폴더(sources.csv, claims.csv). 기본값 data/ledger")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="실재 문헌 검색")
    s.add_argument("query")
    s.add_argument("--rows", type=int, default=5)
    s.add_argument("--add", type=int, nargs="*", metavar="N", help="결과 번호를 대장에 추가")
    s.add_argument("--ref", help="추가할 때 쓸 참고문헌 번호(생략하면 S-001 형식 자동 부여)")

    i = sub.add_parser("import", help="보고서 참고문헌 목록 가져오기")
    i.add_argument("report")

    v = sub.add_parser("verify", help="실재 확인")
    v.add_argument("--ref", nargs="*")
    v.add_argument("--force", action="store_true", help="이미 '확인'인 문헌도 다시 확인")

    c = sub.add_parser("check", help="보고서 본문 인용 점검")
    c.add_argument("report")
    c.add_argument("--out", default="점검결과.md")

    e = sub.add_parser("export", help="엑셀 내보내기")
    e.add_argument("--out", default="자료검토대장.xlsx")

    st = sub.add_parser("set", help="한 문헌의 항목을 직접 기록(수동 확인 결과 등)")
    st.add_argument("ref")
    st.add_argument("pairs", nargs="+", metavar="항목=값",
                    help="예: url=https://... exist_status=확인 access_level=원문 exist_method=수동")

    sub.add_parser("summary", help="현황")

    a = p.parse_args(argv)
    ledger = Ledger.load(a.ledger)

    if a.cmd == "search":
        results = verify.search_all(a.query, rows=a.rows)
        if not results:
            print("검색 결과 없음(네트워크 허용 여부와 검색어를 확인하세요)")
            return 1
        for n, r in enumerate(results, start=1):
            print(f"[{n}] ({r.origin}) {r.title}\n     {r.authors} | {r.year} | {r.venue} "
                  f"{r.volume}({r.issue}) {r.pages} | DOI {r.doi or '-'}")
        for n in a.add or []:
            r = results[n - 1]
            ref = a.ref if a.ref and len(a.add) == 1 else ledger.next_free_ref()
            ledger.upsert(Source(ref_no=ref, title=r.title, authors=r.authors, year=r.year,
                                 source_type=r.source_type, venue=r.venue, volume=r.volume, issue=r.issue,
                                 pages=r.pages, doi=r.doi, url=r.url, exist_status=EXIST_CONFIRMED,
                                 exist_method=r.origin, exist_checked_at=_today(), access_level="미열람"))
            print(f"→ 대장에 [{ref}] 로 추가")
        if a.add:
            ledger.save(a.ledger)

    elif a.cmd == "import":
        pages = refparse.read_text(a.report)
        added = 0
        for src in refparse.parse_references(pages):
            if ledger.get(src.ref_no) is None:
                ledger.upsert(src)
                added += 1
        ledger.sources.sort(key=lambda s: cc._key(s.ref_no))
        ledger.save(a.ledger)
        print(f"참고문헌 {added}건을 새로 등록했습니다(기존 번호는 유지).")

    elif a.cmd == "verify":
        targets = [s for s in ledger.sources if (not a.ref or s.ref_no in a.ref)
                   and (a.force or s.exist_status != EXIST_CONFIRMED)]
        for src in targets:
            verify.verify_source(src)
            print(f"[{src.ref_no}] {src.exist_status:6} ({src.exist_method or '-'}) {src.title[:40]}"
                  + (f"\n      {src.exist_note}" if src.exist_note else ""))
        ledger.save(a.ledger)
        print(f"{len(targets)}건 확인 완료.")

    elif a.cmd == "check":
        pages = refparse.read_text(a.report)
        findings = cc.crosscheck(ledger, pages, refparse.find_citations(pages))
        Path(a.out).write_text(cc.to_markdown(findings), encoding="utf-8")
        print(cc.to_markdown(findings))
        print(f"→ {a.out} 에 저장")

    elif a.cmd == "export":
        ledger.export_xlsx(a.out)
        print(f"→ {a.out} 저장")

    elif a.cmd == "set":
        src = ledger.get(a.ref) or Source(ref_no=a.ref, title="")
        for pair in a.pairs:
            key, _, value = pair.partition("=")
            if key not in SOURCE_FIELDS or key == "ref_no":
                p.error(f"알 수 없는 항목 '{key}'. 사용 가능: {', '.join(SOURCE_FIELDS[1:])}")
            if key == "exist_status" and value not in EXIST_STATUSES:
                p.error(f"exist_status는 {', '.join(EXIST_STATUSES)} 중 하나")
            setattr(src, key, value)
        if any(x.startswith("exist_status=") for x in a.pairs):
            src.exist_checked_at = _today()
            src.exist_method = src.exist_method or "수동"
        ledger.upsert(src)
        ledger.save(a.ledger)
        print(f"[{a.ref}] 기록 완료: {src.exist_status} / {src.title[:40]}")

    elif a.cmd == "summary":
        s = ledger.summary()
        print(f"자료 {s['sources']}건: " + ", ".join(f"{k} {v}" for k, v in s["exist"].items()))
        print(f"인용 {s['claims']}건: " + ", ".join(f"{k} {v}" for k, v in s["verdict"].items()))
    return 0


def _today() -> str:
    import datetime as dt
    return dt.date.today().isoformat()


if __name__ == "__main__":
    sys.exit(main())
