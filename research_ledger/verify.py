"""문헌 실재 확인과 서지 대조.

판정 순서
1) DOI가 있으면 Crossref에서 DOI로 조회 → 제목 비교
2) 없으면 제목으로 Crossref·OpenAlex·KCI 검색 → 가장 비슷한 후보 선택
3) 그래도 못 찾고 URL이 있으면 페이지가 열리는지, 페이지에 제목이 들어 있는지 확인
찾은 후보의 연도·권·호·쪽이 대장과 다르면 '서지불일치'로 표시해 사람이 확인하게 한다.
"""
from __future__ import annotations

import datetime as dt
import re
from difflib import SequenceMatcher

import requests

from . import clients
from .clients import Candidate
from .models import (
    EXIST_CANDIDATE, EXIST_CONFIRMED, EXIST_MISMATCH, EXIST_NOT_FOUND, EXIST_UNVERIFIED, Source,
)

CONFIRM_THRESHOLD = 0.90
CANDIDATE_THRESHOLD = 0.75
# 색인 검색이 의미 있는 유형. 언론보도·법령 등은 URL 확인만 한다.
INDEXED_TYPES = {"학술논문", "연구보고서", "기타"}


def is_korean(text: str) -> bool:
    return bool(re.search(r"[가-힣]", text or ""))


def _index_covers(src: Source) -> bool:
    """못 찾았을 때 '없다'고 말해도 될 만큼 색인이 그 문헌을 포괄하는가.

    Crossref·OpenAlex는 국내 학술지·국책연구 보고서를 거의 싣지 않는다.
    따라서 한글 문헌은 KCI까지 검색한 학술논문일 때만 '찾지못함'으로 판정하고,
    그 밖에는 '미확인'으로 두어 실제 있는 문헌을 환각으로 오판하지 않게 한다.
    """
    if not is_korean(src.title):
        return True
    return src.source_type == "학술논문" and clients.kci_available()


def _why_unverifiable(src: Source) -> str:
    if is_korean(src.title) and src.source_type == "학술논문":
        return ("국내 학술논문은 해외 색인에 거의 없음 — KCI_API_KEY 설정 후 재확인하거나, "
                "KCI·DBpia·KoreaScience 페이지 URL을 기록해 재확인")
    if src.source_type in ("연구보고서", "보도자료", "공문서", "통계자료", "법령", "언론보도", "기타"):
        return "자동 색인 대상이 아님 — 발행기관 원문 URL을 기록하면 페이지·제목으로 자동 확인"
    return "자동 확인 불가 — URL 기록 또는 수동 확인 필요"


def normalize_title(t: str) -> str:
    t = re.sub(r"<[^>]+>", "", t or "")          # Crossref 제목의 <i> 태그 등
    return re.sub(r"[\W_]+", "", t).lower()


def title_similarity(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    # 부제 유무 차이를 허용: 한쪽이 다른 쪽을 그대로 포함하면 높은 점수
    if len(na) >= 15 and (na in nb or nb in na):
        return max(0.92, SequenceMatcher(None, na, nb).ratio())
    return SequenceMatcher(None, na, nb).ratio()


def biblio_differences(src: Source, cand: Candidate) -> list[str]:
    """대장에 적힌 값과 색인 값이 모두 있을 때만 비교한다."""
    diffs = []
    pairs = [("연도", src.year, cand.year), ("권", src.volume, cand.volume),
             ("호", src.issue, cand.issue), ("쪽", src.pages, cand.pages)]
    for label, mine, theirs in pairs:
        if mine and theirs and _norm_num(mine) != _norm_num(theirs):
            diffs.append(f"{label}: 대장 {mine} / 색인 {theirs}")
    return diffs


def _norm_num(s: str) -> str:
    return re.sub(r"[~–—−]", "-", re.sub(r"\s", "", s))


def search_all(query: str, rows: int = 5, session: requests.Session | None = None) -> list[Candidate]:
    """사용 가능한 모든 색인을 검색한다. 한 곳이 실패해도 나머지 결과는 돌려준다."""
    found: list[Candidate] = []
    searches = [clients.crossref_search, clients.openalex_search]
    if clients.kci_available():
        searches.append(clients.kci_search)
    for fn in searches:
        try:
            found.extend(fn(query, rows=rows, session=session))
        except (requests.RequestException, ValueError, KeyError) as e:
            found.append(Candidate(title="", origin=f"{fn.__name__} 실패: {type(e).__name__}"))
    return [c for c in found if c.title]


def best_match(title: str, candidates: list[Candidate]) -> tuple[Candidate | None, float]:
    scored = [(c, title_similarity(title, c.title)) for c in candidates]
    if not scored:
        return None, 0.0
    return max(scored, key=lambda x: x[1])


def verify_source(src: Source, session: requests.Session | None = None,
                  today: str | None = None, fill_missing: bool = True) -> Source:
    """src를 직접 수정해 실재 확인 결과를 기록하고 돌려준다."""
    today = today or dt.date.today().isoformat()
    notes: list[str] = []
    match: Candidate | None = None
    score = 0.0

    if src.doi:
        try:
            c = clients.crossref_by_doi(src.doi, session=session)
        except requests.RequestException as e:
            c = None
            notes.append(f"DOI 조회 실패({type(e).__name__})")
        if c:
            match, score = c, title_similarity(src.title, c.title)
            if score < CANDIDATE_THRESHOLD:
                notes.append(f"DOI는 존재하나 제목이 다름: '{c.title}'")
        else:
            notes.append("DOI가 Crossref에 없음")

    if (match is None or score < CONFIRM_THRESHOLD) and src.source_type in INDEXED_TYPES:
        query = " ".join(x for x in (src.title, src.authors.split(";")[0].split("·")[0], src.year) if x)
        c, sc = best_match(src.title, search_all(query, session=session))
        if c and sc > score:
            match, score = c, sc

    if match and score >= CANDIDATE_THRESHOLD:
        diffs = biblio_differences(src, match)
        if score >= CONFIRM_THRESHOLD:
            src.exist_status = EXIST_MISMATCH if diffs else EXIST_CONFIRMED
        else:
            src.exist_status = EXIST_CANDIDATE
            notes.append(f"유사 문헌(유사도 {score:.2f}): '{match.title}'")
        notes.extend(diffs)
        src.exist_method = match.origin
        if fill_missing:
            for attr in ("doi", "venue", "volume", "issue", "pages", "year", "authors"):
                if not getattr(src, attr) and getattr(match, attr):
                    setattr(src, attr, getattr(match, attr))
    elif src.url:
        u = clients.check_url(src.url, src.title, session=session)
        src.exist_method = "url"
        if u.reachable and u.title_found:
            src.exist_status = EXIST_CONFIRMED
        elif u.reachable:
            src.exist_status = EXIST_CANDIDATE
            notes.append(f"페이지는 열리나(HTTP {u.status}) 제목을 찾지 못함")
        else:
            src.exist_status = EXIST_UNVERIFIED
            notes.append(f"페이지 접속 실패({u.error or u.status}) — 네트워크 허용 여부 확인")
    else:
        if src.doi or (src.source_type in INDEXED_TYPES and _index_covers(src)):
            src.exist_status = EXIST_NOT_FOUND
            notes.append("색인에서 찾지 못함 — 환각 의심, 원문 출처를 직접 확인")
        else:
            src.exist_status = EXIST_UNVERIFIED
            notes.append(_why_unverifiable(src))

    src.exist_checked_at = today
    src.exist_note = " / ".join(notes)
    return src
