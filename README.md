# gyeongbuk-youth-policy

경북 20대 인구이동과 청년 정착정책 보고서의 **선행연구 수집·자료 검토 대장 시스템**입니다.

보고서에 인용한 연구·보고서가 **실제로 있는지** 학술 색인과 발행기관 페이지로 확인하고, 보고서 문장이 **원문과 맞는지**를 대장으로 관리합니다. AI가 만든 가짜 문헌(환각)이나 원문과 다른 수치를 걸러 내는 것이 목적입니다.

## 무엇을 하나요

| 단계 | 명령 | 하는 일 |
|---|---|---|
| 1. 수집 | `search` | 검색어로 Crossref·OpenAlex·KCI에서 **실재하는 문헌**만 찾아 대장에 추가 |
| 2. 등록 | `import` | 보고서 PDF의 참고문헌 목록을 읽어 대장에 한꺼번에 등록 |
| 3. 실재 확인 | `verify` | DOI·제목·발행기관 URL로 문헌이 진짜 있는지 자동 판정 |
| 4. 수동 기록 | `set` | 사람이 원문을 보고 확인한 결과를 대장에 기록 |
| 5. 보고서 점검 | `check` | 보고서 본문의 인용 번호·수치를 대장과 대조해 문제 목록 작성 |
| 6. 내보내기 | `export` | 엑셀 대장(요약·자료 대장·인용 대조 시트) 만들기 |

## 처음 한 번만: 설치

Python 3.10 이상이 필요합니다.

```bash
pip install -r requirements.txt
```

## 사용법

모든 명령은 저장소 폴더에서 실행합니다. 대장은 기본으로 `data/ledger/` 폴더에 저장됩니다.

**선행연구 찾기** — 결과 중 원하는 번호를 `--add`로 대장에 넣습니다.

```bash
python -m research_ledger search "youth migration rural settlement policy"
```

```bash
python -m research_ledger search "youth migration rural settlement policy" --add 2
```

**보고서 참고문헌을 대장에 등록**

```bash
python -m research_ledger import 보고서.pdf
```

**실재 여부 자동 확인** (이미 '확인'된 문헌은 건너뜀)

```bash
python -m research_ledger verify
```

**원문을 직접 보고 확인한 결과 기록**

```bash
python -m research_ledger set 14 url=https://www.dbpia.co.kr/journal/articleDetail?nodeId=NODE11768468 exist_status=확인 access_level=원문
```

**보고서 점검** — 결과가 `점검결과.md`로 저장됩니다.

```bash
python -m research_ledger check 보고서.pdf
```

**엑셀로 내보내기**

```bash
python -m research_ledger export --out data/자료검토대장.xlsx
```

## 대장 구성

`data/ledger/sources.csv` (자료 대장, 문헌 1건 = 1행)와 `data/ledger/claims.csv` (인용 대조, 보고서 문장 1건 = 1행)로 이루어집니다. 두 파일 모두 엑셀에서 바로 열고 고칠 수 있습니다.

**실재 확인 상태**

| 상태 | 뜻 | 할 일 |
|---|---|---|
| 확인 | 색인 또는 발행기관 페이지에서 제목까지 일치 | 없음 |
| 서지불일치 | 문헌은 있으나 연도·권·호·쪽이 대장과 다름 | 확인 메모를 보고 서지 수정 |
| 후보 | 비슷한 문헌만 찾음 | 같은 문헌인지 사람이 확인 |
| 미확인 | 자동으로 확인할 수 없음(국내 보고서·보도 등) | URL을 기록하거나 원문 확인 후 `set` |
| 찾지못함 | 색인이 다루는 범위인데 없음 | **환각 의심** — 원출처를 반드시 찾을 것 |

**인용 판정**: 일치 / 부분일치 / 불일치 / 과잉해석(원문보다 세게 씀) / 미확인

## 알아 둘 점

- **국내 문헌**: Crossref·OpenAlex에는 국내 학술지와 국책연구 보고서가 거의 없습니다. 그래서 실제로 있는 국내 문헌을 '찾지못함'으로 오판하지 않도록, 국내 문헌은 KCI 검색이나 URL 확인으로만 판정하고 그렇지 못하면 '미확인'으로 둡니다.
- **KCI 검색 사용(선택)**: [KCI Open API](https://open.kci.go.kr)에서 무료 키를 받아 환경변수로 넣으면 국내 학술논문도 자동 확인됩니다. KCI 연동은 응답 형식을 기준으로 만들었으나 실제 키로는 아직 시험하지 않았습니다.

```bash
export KCI_API_KEY=발급받은키
```

- **자동 확인의 한계**: '확인'은 문헌이 *존재한다*는 뜻이지 보고서 문장이 *원문과 맞다*는 뜻이 아닙니다. 문장·수치의 일치 여부는 사람이 원문을 읽고 `claims.csv`에 기록해야 합니다. `check`는 대장에 적힌 수치가 보고서에 그대로 있는지, 판정이 '일치'가 아닌 문장이 남았는지를 알려 줍니다.

## 현재 대장 (2026-11-25 검토)

보고서 참고문헌 [1]~[32]와 추가 권장 문헌 1건(일본 총무성 자료)이 들어 있습니다.

- 자료 33건: 확인 13, 미확인 20 (주로 통계표·지자체 안내·언론 보도 → URL 기록 후 확인 필요)
- 인용 22건: 일치 8, 부분일치 6, 과잉해석 5, 불일치 1, 미확인 2
- 점검 결과: [`data/점검결과.md`](data/점검결과.md), 엑셀: `data/자료검토대장.xlsx`

## 테스트

```bash
python -m pytest -q
```
