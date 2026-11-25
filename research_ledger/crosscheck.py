"""보고서 본문과 대장을 맞대어 점검한다.

점검 항목
1. 본문에서 인용했는데 대장에 없는 번호
2. 인용한 문헌 중 실재 확인이 끝나지 않은 것(미확인·후보·찾지못함·서지불일치)
3. 인용 판정이 '일치'가 아닌 문장(불일치·과잉해석·부분일치·미확인)
4. 대장에 기록한 수치가 보고서 본문에 그대로 있는지(보고서를 고친 뒤 대장과 어긋났는지)
5. 근거보다 단정적인 표현(과잉 서술 의심)이 인용 문장에 있는지
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .ledger import Ledger
from .models import EXIST_CONFIRMED, VERDICT_OK
from .refparse import Citation

# 근거보다 세게 쓰기 쉬운 표현. '불확실'·'불분명'처럼 부정형은 제외한다.
STRONG_WORDS = ("분명", "입증", "증명", "확실", "반드시", "모든", "항상", "밝혔다", "보여준다", "드물다")
_STRONG = {w: re.compile(rf"(?<![불])(?<!불){w}") for w in STRONG_WORDS}


@dataclass
class Finding:
    level: str      # 오류 / 주의 / 참고
    kind: str
    ref_no: str
    page: int | None
    message: str


def crosscheck(ledger: Ledger, pages: list[str], citations: list[Citation]) -> list[Finding]:
    out: list[Finding] = []
    full = re.sub(r"\s+", "", "\n".join(pages))
    cited = {}
    for c in citations:
        for n in c.numbers:
            cited.setdefault(n, []).append(c)

    for n, cs in sorted(cited.items(), key=lambda x: _key(x[0])):
        src = ledger.get(n)
        if src is None:
            out.append(Finding("오류", "대장 누락", n, cs[0].page, f"본문 {len(cs)}곳에서 인용했지만 대장에 없음"))
            continue
        if src.exist_status != EXIST_CONFIRMED:
            out.append(Finding("오류" if src.exist_status == "찾지못함" else "주의", "실재 미확인", n, cs[0].page,
                               f"실재 확인 상태 '{src.exist_status}' — {src.exist_note or '확인 필요'}"))
        for c in cs:
            hits = [w for w, rx in _STRONG.items() if rx.search(c.sentence)]
            if hits:
                out.append(Finding("참고", "단정 표현", n, c.page,
                                   f"'{', '.join(hits)}' — 원문이 이 정도로 말하는지 확인: …{c.sentence[-120:]}"))

    for cl in ledger.claims:
        if cl.verdict != VERDICT_OK:
            out.append(Finding("오류" if cl.verdict in ("불일치", "과잉해석") else "주의", f"인용 {cl.verdict}",
                               cl.ref_no, None, f"[{cl.claim_id}] {cl.report_location}: {cl.statement[:80]} → {cl.action}"))
        for v in filter(None, (x.strip() for x in cl.values.split(";"))):
            if re.sub(r"\s+", "", v) not in full:
                out.append(Finding("주의", "수치 미발견", cl.ref_no, None,
                                   f"[{cl.claim_id}] 대장의 수치 '{v}'가 보고서 본문에 없음 — 보고서가 수정됐는지 확인"))

    for s in ledger.sources:
        if s.ref_no.isdigit() and s.ref_no not in cited:
            out.append(Finding("참고", "미인용", s.ref_no, None, "대장에 있으나 본문에서 인용하지 않음"))

    order = {"오류": 0, "주의": 1, "참고": 2}
    return sorted(out, key=lambda f: (order[f.level], _key(f.ref_no)))


def _key(ref: str):
    return (0, int(ref)) if ref.isdigit() else (1, ref)


def to_markdown(findings: list[Finding], title: str = "보고서 인용 점검 결과") -> str:
    lines = [f"# {title}", ""]
    counts = {lvl: sum(f.level == lvl for f in findings) for lvl in ("오류", "주의", "참고")}
    lines.append(" · ".join(f"{k} {v}건" for k, v in counts.items()))
    lines += ["", "쪽 번호는 PDF 쪽(표지 포함) 기준이며, 같은 문헌의 첫 인용 위치만 표시합니다.",
              "", "| 수준 | 유형 | 번호 | 쪽 | 내용 |", "|---|---|---|---|---|"]
    for f in findings:
        msg = f.message.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {f.level} | {f.kind} | [{f.ref_no}] | {f.page or ''} | {msg} |")
    return "\n".join(lines) + "\n"
