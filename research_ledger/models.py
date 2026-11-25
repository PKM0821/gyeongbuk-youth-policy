"""자료 검토 대장의 데이터 구조.

대장은 두 개의 표로 이루어진다.
- 자료(Source): 문헌 1건 = 1행. 실재 여부와 서지 정보를 관리한다.
- 인용(Claim): 보고서가 그 문헌을 근거로 쓴 문장·수치 1건 = 1행. 원문과의 일치 여부를 관리한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, asdict

# 자료 유형
SOURCE_TYPES = ("학술논문", "연구보고서", "통계자료", "보도자료", "언론보도", "법령", "공문서", "기타")

# 실재 확인 상태
EXIST_CONFIRMED = "확인"        # 색인(Crossref/OpenAlex/KCI) 또는 원문 페이지에서 제목까지 일치
EXIST_CANDIDATE = "후보"        # 비슷한 문헌은 찾았으나 제목·연도 등이 완전히 일치하지 않음
EXIST_MISMATCH = "서지불일치"    # 문헌은 있으나 권호·쪽수·연도 등이 대장 기록과 다름
EXIST_UNVERIFIED = "미확인"      # 아직 확인하지 않았거나 찾지 못함
EXIST_NOT_FOUND = "찾지못함"     # 모든 경로에서 검색했으나 없음 → 환각 의심
EXIST_STATUSES = (EXIST_CONFIRMED, EXIST_CANDIDATE, EXIST_MISMATCH, EXIST_UNVERIFIED, EXIST_NOT_FOUND)

# 원문 열람 수준
ACCESS_LEVELS = ("원문", "초록", "보도", "미열람")

# 인용 판정
VERDICT_OK = "일치"
VERDICT_PARTIAL = "부분일치"
VERDICT_BAD = "불일치"
VERDICT_OVERCLAIM = "과잉해석"
VERDICT_UNVERIFIED = "미확인"
VERDICTS = (VERDICT_OK, VERDICT_PARTIAL, VERDICT_BAD, VERDICT_OVERCLAIM, VERDICT_UNVERIFIED)


@dataclass
class Source:
    ref_no: str                      # 보고서의 참고문헌 번호(예: "14"). 보고서와 무관하면 "S-001" 등
    title: str
    authors: str = ""
    year: str = ""
    source_type: str = "기타"
    venue: str = ""                  # 학술지·발행기관·언론사
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    url: str = ""
    exist_status: str = EXIST_UNVERIFIED
    exist_method: str = ""           # crossref / openalex / kci / url / 수동
    exist_checked_at: str = ""       # YYYY-MM-DD
    exist_note: str = ""             # 확인 과정에서 발견한 서지 차이 등
    access_level: str = "미열람"
    note: str = ""


@dataclass
class Claim:
    claim_id: str                    # 예: "14-1"
    ref_no: str
    report_location: str             # 보고서 내 위치(예: "Ⅱ장 1절, 표 3")
    statement: str                   # 보고서가 쓴 문장
    values: str = ""                 # 문장 속 수치(세미콜론 구분). 보고서 본문에 그대로 있는지 자동 대조함
    source_evidence: str = ""        # 원문에서 확인한 내용·위치
    verdict: str = VERDICT_UNVERIFIED
    action: str = ""                 # 수정 권고


SOURCE_FIELDS = [f.name for f in fields(Source)]
CLAIM_FIELDS = [f.name for f in fields(Claim)]

# 엑셀 머리글(한글)
SOURCE_HEADERS = {
    "ref_no": "번호", "title": "제목", "authors": "저자", "year": "연도", "source_type": "유형",
    "venue": "게재처·발행기관", "volume": "권", "issue": "호", "pages": "쪽", "doi": "DOI", "url": "URL",
    "exist_status": "실재 확인", "exist_method": "확인 경로", "exist_checked_at": "확인일",
    "exist_note": "확인 메모", "access_level": "원문 열람", "note": "비고",
}
CLAIM_HEADERS = {
    "claim_id": "인용 ID", "ref_no": "번호", "report_location": "보고서 위치", "statement": "보고서 서술",
    "values": "수치", "source_evidence": "원문 근거", "verdict": "판정", "action": "수정 권고",
}


def to_row(obj) -> dict:
    return asdict(obj)
