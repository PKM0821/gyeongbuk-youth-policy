"""네트워크 없이 도는 테스트. 외부 API 응답은 가짜 세션으로 흉내 낸다."""
import json

import pytest

from research_ledger import clients, crosscheck, refparse, verify
from research_ledger.cli import main
from research_ledger.ledger import Ledger
from research_ledger.models import Claim, Source


class FakeResp:
    def __init__(self, status=200, data=None, text="", ctype="application/json", url=""):
        self.status_code, self._data, self.url = status, data, url
        self.text = text or (json.dumps(data) if data is not None else "")
        self.headers = {"Content-Type": ctype}

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._data

    def raise_for_status(self):
        if not self.ok:
            import requests
            raise requests.HTTPError(str(self.status_code))


class FakeSession:
    """URL 앞부분 → 응답 대응표."""
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, **kw):
        self.calls.append((url, params))
        for prefix, resp in self.routes.items():
            if url.startswith(prefix):
                return resp
        return FakeResp(404, {})


CROSSREF_ITEM = {
    "title": ["Revitalising rural areas through counterurbanisation: Community-oriented policies "
              "for the settlement of urban newcomers"],
    "author": [{"family": "Zollet", "given": "Simona"}, {"family": "Qu", "given": "Meng"}],
    "container-title": ["Habitat International"], "volume": "145", "page": "103022",
    "DOI": "10.1016/j.habitatint.2024.103022", "issued": {"date-parts": [[2024, 3]]}, "type": "journal-article",
}

REPORT = """Ⅱ 선행연구 검토
일자리 격차가 유출의 가장 큰 요인임을 분명히 보여준다. [13~14]
정착 이후 34.9%가 돌아갔다 [16]~[17]. 생활서비스가 부족하면 정착이 불확실하다. [2, 3]
참고자료
[13] 한요셉·윤참나. (2021). 청년층의 지역 간 이동에 관한 연구: 대학 진학을 중심으로. KDI 정책연구시리즈 2021-
09.
[14] 허원창·송현서·전보강. (2024). 지역이탈의 악순환: 출생지의 경제 환경과 청년 취업자의 지역이탈. 지역연구,
40(1), 53~67.
[16] 산업연구원. (2026. 3. 18.). 청년의 지역 이동과 정착. (보도 기준)
[21] Zollet, S., & Qu, M. (2024). Revitalising rural areas through counterurbanisation: Community-
oriented policies for the settlement of urban newcomers. Habitat International.
[31] 경북매일신문(2023. 11. 20.). 청년 연령 기준 비교. https://kbmaeil.com/article/2023112003
77292 (보도 기준)
강의자료: 교재 제3장.
"""


# ---------------- 참고문헌 파싱 ----------------
def test_parse_references():
    refs = {s.ref_no: s for s in refparse.parse_references([REPORT])}
    assert set(refs) == {"13", "14", "16", "21", "31"}
    assert refs["13"].source_type == "연구보고서"
    assert refs["13"].venue == "KDI 정책연구시리즈 2021-09"          # 줄바꿈된 번호 잇기
    s14 = refs["14"]
    assert (s14.authors, s14.year, s14.venue, s14.volume, s14.issue, s14.pages) == \
        ("허원창·송현서·전보강", "2024", "지역연구", "40", "1", "53~67")
    assert s14.source_type == "학술논문"
    assert refs["16"].source_type == "보도자료"
    assert refs["21"].source_type == "학술논문"
    assert "Community-oriented" in refs["21"].title
    assert refs["31"].url == "https://kbmaeil.com/article/202311200377292"  # 끊긴 URL 잇기
    assert "강의자료" not in refs["31"].note


def test_find_citations_and_sentences():
    cites = refparse.find_citations([REPORT.split("참고자료")[0]])
    nums = [c.numbers for c in cites]
    assert ["13", "14"] in nums and ["16", "17"] in nums and ["2", "3"] in nums
    first = next(c for c in cites if c.numbers == ["13", "14"])
    assert "일자리 격차" in first.sentence and first.sentence.endswith("[13~14]")
    second = next(c for c in cites if c.numbers == ["16", "17"])
    assert second.sentence.startswith("정착 이후")          # 앞 문장의 '[13~14]' 뒤에서 시작


def test_expand():
    assert refparse.expand("13~15, 32") == ["13", "14", "15", "32"]
    assert refparse.expand("2, 3") == ["2", "3"]


# ---------------- 실재 확인 ----------------
def test_verify_by_doi_confirms_and_fills():
    sess = FakeSession({"https://api.crossref.org/works/": FakeResp(data={"message": CROSSREF_ITEM})})
    src = Source(ref_no="21", title=CROSSREF_ITEM["title"][0], doi="10.1016/j.habitatint.2024.103022",
                 source_type="학술논문", year="2024")
    verify.verify_source(src, session=sess, today="2026-11-25")
    assert src.exist_status == "확인" and src.exist_method == "crossref"
    assert src.venue == "Habitat International" and src.volume == "145"


def test_verify_detects_biblio_mismatch():
    sess = FakeSession({"https://api.crossref.org/works/": FakeResp(data={"message": CROSSREF_ITEM})})
    src = Source(ref_no="21", title=CROSSREF_ITEM["title"][0], doi="x", source_type="학술논문",
                 year="2023", volume="150")
    verify.verify_source(src, session=sess)
    assert src.exist_status == "서지불일치"
    assert "연도: 대장 2023 / 색인 2024" in src.exist_note


def test_fabricated_english_paper_is_flagged():
    sess = FakeSession({
        "https://api.crossref.org/works": FakeResp(data={"message": {"items": [CROSSREF_ITEM]}}),
        "https://api.openalex.org/works": FakeResp(data={"results": []}),
    })
    src = Source(ref_no="99", title="Youth retention effects of rural housing vouchers in Gyeongbuk",
                 source_type="학술논문")
    verify.verify_source(src, session=sess)
    assert src.exist_status == "찾지못함"
    assert "환각 의심" in src.exist_note


def test_korean_paper_not_in_global_index_is_unverified_not_fabricated(monkeypatch):
    monkeypatch.delenv("KCI_API_KEY", raising=False)
    sess = FakeSession({
        "https://api.crossref.org/works": FakeResp(data={"message": {"items": []}}),
        "https://api.openalex.org/works": FakeResp(data={"results": []}),
    })
    src = Source(ref_no="15", title="위계로짓모형을 활용한 비수도권 청년층의 이주유형별 결정요인 비교분석",
                 source_type="학술논문")
    verify.verify_source(src, session=sess)
    assert src.exist_status == "미확인"          # 실제 있는 국내 논문을 환각으로 몰지 않는다
    assert "KCI" in src.exist_note


def test_url_check_confirms_when_title_on_page():
    title = "청년층의 지역 간 이동에 관한 연구: 대학 진학을 중심으로"
    sess = FakeSession({"https://www.kdi.re.kr": FakeResp(text=f"<html><h1>{title}</h1></html>",
                                                           ctype="text/html")})
    src = Source(ref_no="13", title=title, source_type="연구보고서",
                 url="https://www.kdi.re.kr/research/reportView?pub_no=17435")
    verify.verify_source(src, session=sess)
    assert src.exist_status == "확인" and src.exist_method == "url"


def test_kci_xml_parsing():
    xml = """<MetaData><outputData><record><journalInfo><journal-name>한국경제지리학회지</journal-name>
    <pub-year>2023</pub-year><volume>26</volume><issue>4</issue></journalInfo>
    <articleInfo><title-group><article-title lang="original">위계로짓모형을 활용한 비수도권 청년층의
    이주유형별 결정요인 비교분석</article-title></title-group><author-group><author>우한성</author></author-group>
    <fpage>421</fpage><lpage>442</lpage></articleInfo></record></outputData></MetaData>"""
    [c] = clients.parse_kci_xml(xml)
    assert (c.venue, c.year, c.volume, c.issue, c.pages, c.authors) == \
        ("한국경제지리학회지", "2023", "26", "4", "421-442", "우한성")
    assert verify.title_similarity(c.title, "위계로짓모형을 활용한 비수도권 청년층의 이주유형별 결정요인 비교분석") > 0.9


def test_pages_compare_ignores_dash_style():
    s = Source(ref_no="15", title="t", pages="421~442")
    c = clients.Candidate(title="t", pages="421-442")
    assert verify.biblio_differences(s, c) == []


# ---------------- 대조 점검 ----------------
def test_crosscheck_findings():
    body = REPORT.split("참고자료")[0]
    led = Ledger(
        [Source(ref_no="13", title="a", exist_status="확인"), Source(ref_no="14", title="b", exist_status="미확인"),
         Source(ref_no="16", title="c", exist_status="찾지못함"), Source(ref_no="40", title="d", exist_status="확인")],
        [Claim("16-1", "16", "Ⅱ장", "34.9%가 돌아갔다", values="34.9%; 1.6 년", verdict="과잉해석", action="완화")],
    )
    f = crosscheck.crosscheck(led, [body], refparse.find_citations([body]))
    kinds = {(x.kind, x.ref_no) for x in f}
    assert ("대장 누락", "17") in kinds and ("대장 누락", "2") in kinds
    assert ("실재 미확인", "14") in kinds
    assert any(x.level == "오류" and x.ref_no == "16" and x.kind == "실재 미확인" for x in f)
    assert ("인용 과잉해석", "16") in kinds
    assert ("수치 미발견", "16") in kinds            # '1.6 년'은 본문에 없음
    assert ("미인용", "40") in kinds
    strong = [x for x in f if x.kind == "단정 표현"]
    assert any("분명" in x.message for x in strong)
    assert not any("불확실" in x.message for x in strong)  # 부정형은 제외


# ---------------- 저장·CLI ----------------
def test_ledger_roundtrip_and_xlsx(tmp_path):
    led = Ledger([Source(ref_no="1", title="제목", exist_status="확인")],
                 [Claim("1-1", "1", "Ⅰ장", "문장", verdict="불일치")])
    led.save(tmp_path)
    again = Ledger.load(tmp_path)
    assert again.sources[0].title == "제목" and again.claims[0].verdict == "불일치"
    out = tmp_path / "대장.xlsx"
    again.export_xlsx(out)
    from openpyxl import load_workbook
    wb = load_workbook(out)
    assert wb.sheetnames == ["요약", "자료 대장", "인용 대조"]
    assert wb["자료 대장"]["A1"].value == "번호"


def test_cli_import_set_check(tmp_path, capsys):
    rpt = tmp_path / "report.txt"
    rpt.write_text(REPORT, encoding="utf-8")
    d = str(tmp_path / "ledger")
    assert main(["--ledger", d, "import", str(rpt)]) == 0
    assert main(["--ledger", d, "set", "14", "exist_status=확인", "access_level=원문"]) == 0
    led = Ledger.load(d)
    assert led.get("14").exist_status == "확인" and led.get("14").exist_method == "수동"
    out = tmp_path / "점검.md"
    assert main(["--ledger", d, "check", str(rpt), "--out", str(out)]) == 0
    assert "대장 누락" in out.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--ledger", d, "set", "14", "exist_status=아무거나"])
