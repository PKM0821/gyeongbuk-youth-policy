"""실재하는 문헌을 찾는 검색 클라이언트.

- Crossref: DOI가 있는 국내외 학술지·보고서 (키 불필요)
- OpenAlex: 해외 학술 문헌 색인 (키 불필요)
- KCI: 한국학술지인용색인 Open API (KCI_API_KEY 환경변수 필요)
- URL 확인: 보고서·보도자료처럼 DOI가 없는 자료는 발행기관 페이지가 열리고 제목이 들어 있는지 확인

검색 결과는 모두 Candidate(후보)로 통일해 돌려준다.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import requests

USER_AGENT = "research-ledger/0.1 (literature verification tool)"
TIMEOUT = 20


@dataclass
class Candidate:
    title: str
    authors: str = ""
    year: str = ""
    venue: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    url: str = ""
    origin: str = ""          # crossref / openalex / kci
    source_type: str = "학술논문"
    extra: dict = field(default_factory=dict)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


# ---------------- Crossref ----------------
def crossref_search(query: str, rows: int = 5, session: requests.Session | None = None) -> list[Candidate]:
    s = session or make_session()
    r = s.get("https://api.crossref.org/works",
              params={"query.bibliographic": query, "rows": rows}, timeout=TIMEOUT)
    r.raise_for_status()
    return [_crossref_item(i) for i in r.json()["message"]["items"]]


def crossref_by_doi(doi: str, session: requests.Session | None = None) -> Candidate | None:
    s = session or make_session()
    r = s.get(f"https://api.crossref.org/works/{doi}", timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return _crossref_item(r.json()["message"])


def _crossref_item(i: dict) -> Candidate:
    year = ""
    for k in ("published-print", "published-online", "issued"):
        parts = (i.get(k) or {}).get("date-parts") or [[None]]
        if parts[0] and parts[0][0]:
            year = str(parts[0][0])
            break
    authors = "; ".join(
        " ".join(p for p in (a.get("family"), a.get("given")) if p) or a.get("name", "")
        for a in i.get("author", [])
    )
    kind = i.get("type", "")
    return Candidate(
        title=(i.get("title") or [""])[0],
        authors=authors,
        year=year,
        venue=(i.get("container-title") or [""])[0] or i.get("publisher", ""),
        volume=i.get("volume", ""),
        issue=i.get("issue", ""),
        pages=i.get("page", "") or i.get("article-number", ""),
        doi=i.get("DOI", ""),
        url=i.get("URL", ""),
        origin="crossref",
        source_type="연구보고서" if kind in ("report", "monograph", "book") else "학술논문",
    )


# ---------------- OpenAlex ----------------
def openalex_search(query: str, rows: int = 5, session: requests.Session | None = None) -> list[Candidate]:
    s = session or make_session()
    r = s.get("https://api.openalex.org/works", params={"search": query, "per-page": rows}, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for i in r.json().get("results", []):
        b = i.get("biblio") or {}
        src = ((i.get("primary_location") or {}).get("source") or {})
        pages = "-".join(p for p in (b.get("first_page"), b.get("last_page")) if p)
        out.append(Candidate(
            title=i.get("display_name") or "",
            authors="; ".join(a["author"]["display_name"] for a in i.get("authorships", []) if a.get("author")),
            year=str(i.get("publication_year") or ""),
            venue=src.get("display_name", "") or "",
            volume=b.get("volume") or "",
            issue=b.get("issue") or "",
            pages=pages,
            doi=(i.get("doi") or "").replace("https://doi.org/", ""),
            url=i.get("id", ""),
            origin="openalex",
        ))
    return out


# ---------------- KCI (한국학술지인용색인) ----------------
KCI_ENDPOINT = "https://open.kci.go.kr/po/openapi/openApiSearch.kci"


def kci_available() -> bool:
    return bool(os.environ.get("KCI_API_KEY"))


def kci_search(title: str, rows: int = 5, session: requests.Session | None = None) -> list[Candidate]:
    """KCI 논문 검색. https://open.kci.go.kr 에서 발급받은 키를 KCI_API_KEY 환경변수에 넣어야 한다."""
    key = os.environ.get("KCI_API_KEY")
    if not key:
        return []
    s = session or make_session()
    r = s.get(KCI_ENDPOINT, params={"apiCode": "articleSearch", "key": key, "title": title,
                                    "displayCount": rows}, timeout=TIMEOUT)
    r.raise_for_status()
    return parse_kci_xml(r.text)


def parse_kci_xml(text: str) -> list[Candidate]:
    root = ET.fromstring(text)
    out = []
    for rec in _iter_local(root, "record"):
        def first(name):
            el = next(_iter_local(rec, name), None)
            return (el.text or "").strip() if el is not None and el.text else ""
        titles = list(_iter_local(rec, "article-title"))
        title = next((t.text for t in titles if t.get("lang") in ("original", None) and t.text), "")
        authors = "; ".join((a.text or "").strip() for a in _iter_local(rec, "author") if a.text)
        fpage, lpage = first("fpage"), first("lpage")
        out.append(Candidate(
            title=(title or "").strip(),
            authors=authors,
            year=first("pub-year"),
            venue=first("journal-name"),
            volume=first("volume"),
            issue=first("issue"),
            pages="-".join(p for p in (fpage, lpage) if p),
            doi=first("doi"),
            url=first("url"),
            origin="kci",
        ))
    return out


def _iter_local(el, name):
    for e in el.iter():
        if e.tag.split("}")[-1] == name:
            yield e


# ---------------- URL 확인 ----------------
@dataclass
class UrlCheck:
    reachable: bool
    status: int
    title_found: bool
    final_url: str = ""
    error: str = ""


def check_url(url: str, expect_title: str = "", session: requests.Session | None = None) -> UrlCheck:
    s = session or make_session()
    try:
        r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as e:
        return UrlCheck(False, 0, False, error=type(e).__name__)
    found = False
    if expect_title and r.ok and "text" in r.headers.get("Content-Type", "text/html"):
        found = _norm(expect_title)[:30] in _norm(r.text)
    return UrlCheck(r.ok, r.status_code, found, final_url=r.url)


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", s or "").lower()
