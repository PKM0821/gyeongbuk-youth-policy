"""대장 저장·불러오기(CSV)와 엑셀 내보내기."""
from __future__ import annotations

import csv
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .models import (
    CLAIM_FIELDS, CLAIM_HEADERS, EXIST_STATUSES, SOURCE_FIELDS, SOURCE_HEADERS, VERDICTS,
    Claim, Source,
)

SOURCES_FILE = "sources.csv"
CLAIMS_FILE = "claims.csv"


class Ledger:
    def __init__(self, sources: list[Source] | None = None, claims: list[Claim] | None = None):
        self.sources = sources or []
        self.claims = claims or []

    # ---------- 조회·수정 ----------
    def get(self, ref_no: str) -> Source | None:
        return next((s for s in self.sources if s.ref_no == ref_no), None)

    def upsert(self, source: Source) -> None:
        for i, s in enumerate(self.sources):
            if s.ref_no == source.ref_no:
                self.sources[i] = source
                return
        self.sources.append(source)

    def next_free_ref(self, prefix: str = "S-") -> str:
        used = {s.ref_no for s in self.sources}
        n = 1
        while f"{prefix}{n:03d}" in used:
            n += 1
        return f"{prefix}{n:03d}"

    def claims_for(self, ref_no: str) -> list[Claim]:
        return [c for c in self.claims if c.ref_no == ref_no]

    # ---------- 파일 입출력 ----------
    @classmethod
    def load(cls, directory: str | Path) -> "Ledger":
        d = Path(directory)
        return cls(
            [Source(**_clean(r, SOURCE_FIELDS)) for r in _read_csv(d / SOURCES_FILE)],
            [Claim(**_clean(r, CLAIM_FIELDS)) for r in _read_csv(d / CLAIMS_FILE)],
        )

    def save(self, directory: str | Path) -> None:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        _write_csv(d / SOURCES_FILE, SOURCE_FIELDS, [asdict(s) for s in self.sources])
        _write_csv(d / CLAIMS_FILE, CLAIM_FIELDS, [asdict(c) for c in self.claims])

    def summary(self) -> dict:
        return {
            "sources": len(self.sources),
            "exist": Counter(s.exist_status for s in self.sources),
            "claims": len(self.claims),
            "verdict": Counter(c.verdict for c in self.claims),
        }

    def export_xlsx(self, path: str | Path) -> None:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill

        fills = {
            "확인": "C6EFCE", "일치": "C6EFCE",
            "후보": "FFEB9C", "부분일치": "FFEB9C", "미확인": "FFEB9C", "서지불일치": "FFEB9C",
            "찾지못함": "FFC7CE", "불일치": "FFC7CE", "과잉해석": "FFC7CE",
        }
        wb = Workbook()

        ws = wb.active
        ws.title = "요약"
        s = self.summary()
        ws.append(["자료 검토 대장 요약"])
        ws["A1"].font = Font(bold=True, size=13)
        ws.append([])
        ws.append(["자료 수", s["sources"]])
        for st in EXIST_STATUSES:
            ws.append([f"  실재 확인: {st}", s["exist"].get(st, 0)])
        ws.append(["인용 수", s["claims"]])
        for v in VERDICTS:
            ws.append([f"  판정: {v}", s["verdict"].get(v, 0)])
        ws.column_dimensions["A"].width = 24

        def sheet(title, headers, rows, status_key, widths):
            w = wb.create_sheet(title)
            keys = list(headers)
            w.append([headers[k] for k in keys])
            for c in w[1]:
                c.font = Font(bold=True)
                c.fill = PatternFill("solid", fgColor="D9E1F2")
            for r in rows:
                w.append([r[k] for k in keys])
                color = fills.get(r[status_key])
                if color:
                    w.cell(row=w.max_row, column=keys.index(status_key) + 1).fill = PatternFill("solid", fgColor=color)
            for i, k in enumerate(keys, start=1):
                w.column_dimensions[w.cell(row=1, column=i).column_letter].width = widths.get(k, 12)
            for row in w.iter_rows(min_row=2):
                for c in row:
                    c.alignment = Alignment(wrap_text=True, vertical="top")
            w.freeze_panes = "B2"
            w.auto_filter.ref = w.dimensions

        sheet("자료 대장", SOURCE_HEADERS, [asdict(x) for x in self.sources], "exist_status",
              {"title": 40, "authors": 18, "venue": 22, "doi": 24, "url": 30, "exist_note": 40, "note": 30})
        sheet("인용 대조", CLAIM_HEADERS, [asdict(x) for x in self.claims], "verdict",
              {"report_location": 16, "statement": 50, "values": 16, "source_evidence": 50, "action": 40})
        wb.save(path)


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    # utf-8-sig: 엑셀에서 바로 열어도 한글이 깨지지 않는다
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _clean(row: dict, allowed: list[str]) -> dict:
    return {k: (row.get(k) or "") for k in allowed}
