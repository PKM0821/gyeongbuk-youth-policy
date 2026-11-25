"""보고서(PDF·텍스트)에서 참고문헌 목록과 본문 인용 번호를 뽑는다."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import Source

REF_HEADINGS = ("참고자료", "참고문헌", "References", "REFERENCES")
END_HEADINGS = ("부록", "Appendix", "첨부")


def read_text(path: str | Path) -> list[str]:
    """쪽별 텍스트 목록을 돌려준다. PDF가 아니면 전체를 한 쪽으로 본다."""
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        import pdfplumber
        with pdfplumber.open(p) as pdf:
            return [(pg.extract_text() or "") for pg in pdf.pages]
    return [p.read_text(encoding="utf-8")]


# ---------------- 참고문헌 목록 ----------------
_ENTRY = re.compile(r"^\s*\[(\d+)\]\s*(.+)$")


def reference_block(pages: list[str]) -> str:
    text = "\n".join(pages)
    start = max((text.rfind("\n" + h) for h in REF_HEADINGS), default=-1)
    if start < 0:
        return ""
    block = text[start:]
    ends = [block.find("\n" + h) for h in END_HEADINGS if block.find("\n" + h) > 0]
    return block[: min(ends)] if ends else block


def split_entries(block: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    current = None
    for line in block.splitlines():
        m = _ENTRY.match(line)
        if m:
            current = m.group(1)
            entries[current] = m.group(2).strip()
        elif current and line.strip() and not re.fullmatch(r"\s*\d+\s*", line):
            nxt = line.strip()
            if re.match(r"^[^\s\[\]]{1,12}:\s", nxt):      # '강의자료: …' 같은 목록 밖 메모 → 항목 종료
                current = None
                continue
            prev = entries[current]
            # 줄바꿈으로 끊긴 URL·'2021-\n09' 같은 번호는 공백 없이 잇는다
            glue = "" if re.search(r"(https?://\S+|-)$", prev) and re.match(r"^[\w/%.\-?=&]", nxt) else " "
            entries[current] = prev + glue + nxt
    return entries


_HEAD = re.compile(r"^(?P<authors>[^()]+?)\.?\s*\((?P<date>\d{4}[^)]*)\)\.?\s*(?P<rest>.*)$")
_VOL = re.compile(r"(\d+)\s*\((\d+)\)\s*,?\s*(\d+\s*[~\-–]\s*\d+)?")
_URL = re.compile(r"https?://\S+")


def parse_entry(ref_no: str, raw: str) -> Source:
    raw = re.sub(r"\s+", " ", raw).strip()
    url = (_URL.search(raw) or [""])[0] if _URL.search(raw) else ""
    m = _HEAD.match(raw)
    if m:
        authors, date, rest = m.group("authors").strip(), m.group("date"), m.group("rest")
        year = date[:4]
    else:
        authors, year, rest = "", "", raw
    note_parts = re.findall(r"\(([^()]*(?:보도|기준)[^()]*)\)", rest)   # '(보도 기준)' 같은 메모는 비고로
    rest = re.sub(r"\s*\([^()]*(?:보도|기준)[^()]*\)", "", rest).strip()
    parts = [p.strip() for p in re.split(r"\.\s+", rest) if p.strip()]
    if not m and len(parts) > 1 and not re.search(r"제\s*\d+\s*조", parts[0]):
        # '국가데이터처. 국내인구이동통계. …' 처럼 발행기관이 맨 앞에 오는 항목
        authors, parts = parts[0], parts[1:]
        yr = re.search(r"(19|20)\d{2}", " ".join(parts))
        year = yr.group(0) if yr else ""
    title = parts[0] if parts else rest
    venue = parts[1] if len(parts) > 1 else ""
    volume = issue = pages = ""
    vm = _VOL.search(rest)
    if vm:
        volume, issue = vm.group(1), vm.group(2)
        pages = re.sub(r"\s", "", vm.group(3) or "")
        venue = re.sub(r",?\s*\d+\s*\(\d+\).*$", "", venue)
    if url:
        venue = venue.replace(url, "").strip()
    return Source(
        ref_no=ref_no, title=title.rstrip("."), authors=authors, year=year,
        source_type=guess_type(raw, authors), venue=venue.rstrip(".,"), volume=volume, issue=issue,
        pages=pages, url=url,
        note=" ".join([f"[{n}]" for n in note_parts] + [f"원문 항목: {raw}"]),
    )


def guess_type(raw: str, authors: str = "") -> str:
    if re.search(r"(일보|신문|뉴스)$", authors) or re.search(r"^[^.]*(일보|신문|뉴스)[.(]", raw):
        return "언론보도"
    if re.search(r"\d+\s*\(\d+\)|학회지|Journal|International|Review|연구,", raw):
        return "학술논문"
    if "보도 기준" in raw or "보도자료" in raw:
        return "보도자료"        # 기관 발표를 언론 보도로 확인한 자료
    if re.search(r"(법|조례)\s*제\s*\d+\s*조|국가법령정보센터", raw):
        return "법령"
    if re.search(r"DT_|통계표|국내인구이동통계|주민등록인구", raw):
        return "통계자료"
    if re.search(r"연구원|정책연구|연구보고서|연구시리즈|KDI", raw):
        return "연구보고서"
    if re.search(r"과업지시서|제안요청서|업무계획|회의록", raw):
        return "공문서"
    return "기타"


def parse_references(pages: list[str]) -> list[Source]:
    return [parse_entry(n, raw) for n, raw in split_entries(reference_block(pages)).items()]


# ---------------- 본문 인용 ----------------
_CITE = re.compile(r"\[(\d+(?:\s*[~\-–]\s*\d+)?(?:\s*,\s*\d+(?:\s*[~\-–]\s*\d+)?)*)\]")


@dataclass
class Citation:
    page: int
    numbers: list[str]
    sentence: str


def expand(spec: str) -> list[str]:
    out = []
    for part in spec.split(","):
        part = part.strip()
        m = re.match(r"(\d+)\s*[~\-–]\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            out.extend(str(i) for i in range(a, b + 1)) if a <= b and b - a < 100 else out.append(part)
        elif part:
            out.append(part)
    return out


def find_citations(pages: list[str]) -> list[Citation]:
    """참고문헌 목록 이전 본문에서 '[2, 3]', '[13~19]', '[16]~[19]' 형태의 인용을 찾는다."""
    cites = []
    for pno, page in enumerate(pages, start=1):
        if any(page.lstrip().startswith(h) for h in REF_HEADINGS):
            break
        flat = re.sub(r"\s+", " ", page)
        flat = re.sub(r"\[(\d+)\]\s*~\s*\[(\d+)\]", r"[\1~\2]", flat)   # [16]~[19] → [16~19]
        for m in _CITE.finditer(flat):
            cites.append(Citation(pno, expand(m.group(1)), _sentence_before(flat, m.start(), m.end())))
    return cites


def _sentence_before(flat: str, start: int, end: int) -> str:
    """인용 표시 바로 앞 문장. '…컸다. [2~4]'처럼 마침표 뒤에 붙은 인용도 처리한다."""
    stop = start
    while stop > 0 and flat[stop - 1] in " .":       # 인용 앞의 마침표·공백 건너뛰기
        stop -= 1
    prev_end = max(flat.rfind(". ", 0, stop), flat.rfind("] ", 0, stop))
    begin = prev_end + 2 if prev_end >= 0 else max(0, stop - 200)
    return flat[begin:end].strip()[-300:]
