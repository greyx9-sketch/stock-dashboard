"""AI 에게 넘길 **리서치 지시서**를 만든다.

## 무엇이 바뀌었나 (2026-09-14)

이 프로젝트는 원래 Anthropic API 로 공시를 직접 분석해 카드로 보여줬다. 그 경로를
**화면에서 걷어내고** 이것으로 바꿨다. 이유가 둘이다.

1. **돈.** 분석 한 건에 200~410원이 들었다(실측). 사용자는 claude.ai 구독이 있고,
   붙여넣고 묻는 것은 **추가 비용이 0원**이다.
2. **더 정확하다.** 우리 API 분석은 "원문에 없는 것을 쓰지 마라"가 첫째 규칙이었다.
   그래서 최근 뉴스도, 업황도, 경쟁사 동향도 모른다 — 일부러 그렇게 만든 것이다.
   붙여넣는 쪽은 **웹을 직접 뒤지고 원문 링크를 열어 볼 수 있다.**

그래서 여기서 만드는 것은 분석 결과가 아니라 **조사 지시서**다. 우리가 확실히 아는
것(공시 원자료에서 계산한 수치, 공시 원문 주소)을 싣고, 나머지는 받는 쪽이 찾게 한다.

## 우리가 싣는 것과 시키는 것의 경계

**싣는 것 — 우리가 계산한 확정 자료.** 재무·밸류에이션·시세·공시 목록. 전부 원자료에서
나온 숫자다. 절대 규칙 3은 LLM 이 수치를 **만드는** 것을 막는 규칙이지, 우리 계산값을
프롬프트에 넣는 것을 막지 않는다. 오히려 넣어야 한다 — 숫자를 안 주면 받는 쪽이 기억으로
지어낸다. 그래서 프롬프트가 "이 숫자를 우선하라"고 못 박는다.

**시키는 것 — 우리가 못 하는 것.** 원문 정독, 웹 리서치, 업황 대조, 판단.

## 왜 화면이 아니라 서버에서 만드는가

자료가 전부 여기 있고, **파이썬 테스트가 있다.** 프롬프트는 한 글자가 바뀌면 결과가
달라지는 물건이라 회귀로 묶어 둘 자리가 필요하다. 화면에서 문자열을 이어 붙이면
그걸 지킬 방법이 없다(프론트엔드에는 테스트 설정이 없다).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from app.clients.dart import DartClient, DartError
from app.clients.sec import SecClient, SecError, UsFiling
from app.clock import today_kst
from app.services import (
    dart_corps,
    dart_financials,
    dart_quarterly,
    sec_companies,
    sec_financials,
    valuation as valuation_service,
)

logger = logging.getLogger(__name__)

# 공시를 얼마나 거슬러 올라가 몇 건이나 실을지.
#
# **넉넉히 받아서 우리가 골라야 한다.** 최근 15건을 그냥 실었더니 삼성전자 목록의
# 아홉 건이 "임원ㆍ주요주주특정증권등소유상황보고서" 였고, 정작 사업보고서와
# 분기보고서가 목록에 없었다. 임원 한 사람의 지분 신고가 기업 분석의 자리를 먹은 것이다.
#
# 그래서 많이 받아 놓고 **같은 보고서명은 최신 한 건만** 남긴다. 정기보고서는 이름에
# 기간이 붙어 있어(「사업보고서 (2025.12)」) 저절로 서로 다른 이름이 되므로 살아남는다.
DISCLOSURE_DAYS = 365
DISCLOSURE_FETCH = 100
DISCLOSURE_COUNT = 15

# 정기보고서(사업·반기·분기)는 따로 받는다. 2년이면 사업보고서 두 번이 들어와
# 전년과 견줄 수 있다.
PERIODIC_DAYS = 730
PERIODIC_COUNT = 6

ANNUAL_YEARS = 6
QUARTER_COUNT = 8

FS_LABEL = {"CFS": "연결", "OFS": "별도"}


class PromptError(Exception):
    """지시서를 만들 수 없음. 메시지를 그대로 화면에 보여줄 수 있게 쓴다."""


@dataclass
class Prompt:
    symbol: str
    name: str
    market: str  # KR / US
    preset: str
    text: str
    # 무엇이 담겼는지 화면에 보여준다. 붙여넣기 전에 눈으로 확인할 수 있어야 한다.
    included: list[str] = field(default_factory=list)
    # 못 담은 것. 조용히 비우지 않는다.
    missing: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 지시문

# 보고서 종류. 자료 블록은 같고 **시키는 일만** 바뀐다.
PRESETS: dict[str, dict[str, str]] = {
    "report": {
        "label": "기업 분석 보고서",
        "hint": "원문을 읽고 웹까지 조사해 종합 보고서를 쓰게 합니다",
        "ask": """\
## 해 주실 일

**먼저 조사하고, 그다음에 쓰십시오.** 아래 자료만 정리해 옮기는 것은 도움이 되지 않습니다.

1. **위 공시 원문 링크를 열어 읽으십시오.** 최신 사업보고서·분기보고서가 우선입니다.
   사업의 내용, 경영진의 분석, 소송·제재·우발부채를 직접 확인하십시오.
2. **웹에서 최근 상황을 찾으십시오.** 업황, 전방 수요, 가격 동향, 규제 변화,
   경쟁사 움직임, 그리고 위 자료 이후에 나온 실적·뉴스.
3. 그런 다음 아래 차례로 보고서를 쓰십시오.

## 보고서에 담을 것

1. **한 문장 요약** — 이 회사가 무엇으로 돈을 버는지. 업계 용어 없이, 중학생에게
   말하듯. "플랫폼", "솔루션", "생태계" 같은 말이 들어가면 실패한 문장입니다.
2. **사업 구조와 돈의 흐름** — 무엇을 사와서, 무엇으로 바꿔, 누구에게 파는가.
   부문이 여럿이면 각 부문이 전체에서 차지하는 위치까지.
3. **실적 해석** — 위 표의 숫자가 **왜 그렇게 움직였는지**. 숫자를 다시 나열하지 말고
   원인을 쓰십시오. 꺾인 해가 있으면 그 해에 무슨 일이 있었는지 반드시 짚으십시오.
4. **최근 공시에서 읽히는 것** — 위 공시 목록에서 중요한 것을 골라 무슨 뜻인지.
   제목만 보고 쓰지 말고 원문을 열어 확인하십시오.
5. **위험** — 각 위험에 **성격**(규제·경쟁·공급망·고객집중·수요가격·기술·재무·소송)과
   **시점**(이미 진행 중 / 다가오는 / 잠재적)을 붙이십시오.
6. **경쟁 구도** — 누구와 무엇으로 싸우는가. 회사가 주장하는 우위와 그 근거의 강도.
7. **지금 확인해야 할 것** — 다음에 무엇을 보면 이 그림이 맞는지 틀리는지 알 수 있는가.
   관찰 가능한 지표나 사건으로 적으십시오.""",
    },
    "filings": {
        "label": "최근 공시 해설",
        "hint": "최근 공시들을 열어 읽고 무슨 일이 벌어지는지 풀어 줍니다",
        "ask": """\
## 해 주실 일

**위 공시 목록의 원문을 직접 열어 읽고**, 이 회사에 지금 무슨 일이 벌어지고 있는지
풀어 주십시오. 제목만 보고 짐작해 쓰지 마십시오.

1. 목록에서 **중요한 것부터 고르십시오.** 정기보고서, 주요사항보고, 지분 변동,
   대규모 계약·투자, 소송·제재가 대체로 그렇습니다. 무엇을 왜 골랐는지 밝히십시오.
2. 고른 공시마다: **무엇을 알렸나 → 왜 냈나 → 무엇이 달라지나**.
3. 여러 공시가 한 흐름을 이루면 묶어서 그 흐름을 설명하십시오.
4. 웹에서 각 공시에 대한 시장의 반응·해설을 찾아 덧붙이되, 출처와 날짜를 밝히십시오.
5. 마지막에 **아직 알 수 없는 것**을 남기십시오.""",
    },
    "bull_bear": {
        "label": "강세·약세 양쪽",
        "hint": "같은 자료로 두 시각을 세우고 무엇이 갈림길인지 찾습니다",
        "ask": """\
## 해 주실 일

같은 자료로 **두 시각을 각각 가장 강하게** 세워 주십시오. 한쪽을 약하게 만들어
다른 쪽을 띄우지 마십시오.

1. **먼저 조사하십시오** — 위 공시 원문을 읽고, 웹에서 업황과 최근 소식을 찾으십시오.
2. **강세 논거** 3~5개. 각각 근거와 그 근거의 출처.
3. **약세 논거** 3~5개. 같은 기준으로.
4. **갈림길** — 두 시각이 갈라지는 **핵심 쟁점**이 무엇인지. 보통 한두 개입니다.
5. 그 쟁점마다 **무엇이 관찰되면 어느 쪽이 맞는 것인지** 적으십시오.
   관찰 가능한 지표·사건으로 적어야 합니다. "업황이 좋아지면"은 안 됩니다.

매수·매도 의견이나 목표주가를 쓰지 마십시오. **논거와 검증 방법**을 주십시오 —
판단은 읽는 사람이 합니다.""",
    },
    "peers": {
        "label": "동종업계 비교",
        "hint": "경쟁사를 직접 찾아 같은 잣대로 견줍니다",
        "ask": """\
## 해 주실 일

이 회사를 **같은 판에서 경쟁하는 회사들과 견줘** 주십시오.

1. **경쟁사를 먼저 찾으십시오.** 위 공시 원문과 웹에서 찾되, 왜 그 회사를 골랐는지
   근거를 대십시오. 업종 분류가 같다는 것만으로는 부족합니다 — **같은 고객을 두고
   싸우는지**가 기준입니다.
2. 비교 항목을 정하고(사업 구조 / 돈을 내는 쪽 / 원가 구조 / 성장률 / 수익성 /
   밸류에이션 / 규제 노출) 표로 채우십시오.
3. 숫자를 쓸 때는 **출처와 기준 시점**을 반드시 밝히십시오. 회계 기준과 결산월이
   다르면 그 사실을 적고 비교 가능하게 맞추십시오.
4. 어느 쪽이 낫다는 결론보다 **무엇이 다른지와 그 차이가 어디서 오는지**를 쓰십시오.
5. 마지막에 이 비교의 한계를 적으십시오.""",
    },
}

DEFAULT_PRESET = "report"

# 모든 지시문 끝에 **그대로 같이** 붙는다. 무엇을 시키든 결과물의 모양은 같아야 한다.
#
# 왜 넣었나: 첫 실사용에서 NVDA 기업 분석이 훌륭한 내용으로 돌아왔는데 **글벽**이었다.
# 돈의 흐름도, 부문 비중, 6개년 실적, 위험의 성격×시점 — 전부 그림이 더 빨리 읽히는
# 것들이 문단으로 적혀 있었다. 내용을 더 시킬 게 아니라 **모양을 시켜야** 했다.
#
# 표(내용 종류 → 그림 종류)가 이 블록의 핵심이다. "보기 좋게 만들어라"는 말은 아무것도
# 바꾸지 못한다. 무엇을 무엇으로 그릴지 짝지어 줘야 실제로 그림이 나온다.
OUTPUT_RULES = """\
## 결과물 — **아티팩트 한 장으로 만들어 주십시오**

답을 채팅 글로 늘어놓지 마시고 **HTML 아티팩트**로 만들어 주십시오. 읽는 사람은 이것을
띄워 놓고 봅니다. 같은 내용이라도 문단으로 늘어놓으면 읽히지 않습니다.

### 무엇을 무엇으로 그리나

**글로 설명하면 세 문장이 걸리는 것은 대개 그림 한 장이면 됩니다.**

| 내용 | 그림 |
| --- | --- |
| 사업 구조·돈의 흐름 | **흐름도** — 사오는 것 → 값을 붙이는 지점 → 돈을 내는 쪽. 상자와 화살표로 잇고, 돈은 반대 방향이라는 것을 표시 |
| 전체 구조 한눈에 | **마인드맵** — 가운데에 회사, 가지로 사업부문·고객·위험·경쟁사 |
| 시간에 따른 숫자 | **막대 또는 선 그래프** — 위 표의 연간·분기 실적 |
| 구성비 | **가로 누적 막대** — 도넛보다 여러 해를 나란히 견주기 쉽습니다 |
| 위험 | **2축 지도** — 가로는 성격, 세로는 시점(이미 진행 중 / 다가오는 / 잠재적) |
| 경쟁 구도 | **비교표** 또는 축이 뚜렷한 **포지셔닝 맵** |
| 확인할 것 | **체크리스트** — 무엇을 보면 어느 쪽인지 판별되는지를 함께 |

### 그림에서 지킬 것

1. **그림에 넣는 숫자는 위 표의 값을 쓰십시오.** 축과 막대에 실제 값을 적으십시오.
   위 표에 없는 숫자를 그림에 넣어야 한다면 **그림 안에 출처를 적으십시오.**
   그림은 글보다 더 사실처럼 보입니다 — 지어낸 값이 그래프가 되면 더 위험합니다.
2. **그림 하나에 질문 하나.** 이 그림이 무슨 질문에 답하는지를 제목으로 다십시오.
   답하는 질문이 없으면 장식이므로 넣지 마십시오.
3. **글로 충분한 것을 그림으로 만들지 마십시오.** 항목 셋짜리 목록은 목록이 낫습니다.
4. 그림마다 **한 줄 해석**을 붙이십시오. 그림만 있으면 어디를 봐야 할지 모릅니다.
5. 추정값과 2차 출처는 **그림 안에서도** 그렇게 표시하십시오(점선, '추정' 꼬리표 등).

### 만드는 법

- 그림은 **인라인 SVG 와 CSS 로 직접** 그리십시오. 차트 라이브러리는 로딩에 실패하면
  빈 화면이 되고, 이 보고서는 나중에 다시 열어 볼 것입니다.
- 한국어로 쓰되 회사명·제품명은 원문 표기를 유지하십시오.
- **좁은 화면(400px)에서도 가로 스크롤 없이** 읽히게 하십시오.
- 색은 **뜻이 있을 때만** 쓰십시오. 증가·감소처럼 방향이 있는 것에만 쓰고 단순 분류에는
  쓰지 마십시오. 색만으로 뜻을 나르지 말고 글자나 모양을 함께 쓰십시오.
- 맨 위에 **한 문장 요약**과 **이 보고서가 답하는 질문 3~5개**를 목차처럼 두십시오."""


HEADER_RULES = """\
## 이 자료를 읽는 법

- 아래 **수치는 공시 원자료에서 직접 계산한 값**입니다(국내 DART XBRL / 미국 SEC XBRL).
  웹에서 찾은 값과 어긋나면 **아래 값을 우선**하고, 차이가 나면 그 사실을 적어 주십시오.
- 아래에는 **해석이 하나도 없습니다.** 숫자와 원문 주소뿐입니다. 해석은 당신 몫입니다.
- 빈칸은 공시에 없거나 아직 받지 못한 값입니다. **비어 있다고 지어내지 마십시오.**
- 새 숫자를 쓸 때는 반드시 **출처와 기준 시점**을 밝혀 주십시오.
- 사실과 판단을 갈라 쓰십시오. 추측은 추측이라고 표시하십시오."""


# ---------------------------------------------------------------- 표 만들기


def _num(value: int | None) -> str:
    return f"{value:,}" if value is not None else "—"


def _pct(value: object) -> str:
    return f"{value}%" if value not in (None, "") else "—"


def _table(head: list[str], rows: list[list[str]]) -> str:
    """파이프 표. 붙여넣었을 때 받는 쪽이 표로 읽는다."""
    lines = [f"| {' | '.join(head)} |", f"| {' | '.join('---' for _ in head)} |"]
    lines += [f"| {' | '.join(row)} |" for row in rows]
    return "\n".join(lines)


def _dedupe_by_name(items: list, limit: int) -> list:
    """같은 보고서명은 **최신 한 건만** 남기고 최신순으로 `limit` 건까지.

    지분 신고처럼 같은 이름이 매주 반복되는 공시가 목록을 통째로 먹는 것을 막는다.
    정기보고서는 이름에 기간이 붙어 있어 서로 다른 이름이라 함께 살아남는다.
    """
    seen: set[str] = set()
    kept = []
    for item in items:  # DART 가 최신순으로 준다
        name = item.report_name.strip()
        # 정정 표시는 이름을 다르게 만들지만 같은 서류다. 앞머리 대괄호를 떼고 견준다.
        key = name.split("]", 1)[-1].strip() if name.startswith("[") else name
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
        if len(kept) >= limit:
            break
    return kept


def _with_q4(
    quarters: list, annual: list
) -> list[tuple[int, int, int | None, int | None, int | None, bool]]:
    """분기 목록에 **4분기를 채워 넣는다.** (연도, 분기, 매출, 영업이익, 순이익, 파생인가)

    DART 에는 4분기 보고서가 없다 — 3분기까지만 분기보고서가 나오고 4분기는 사업보고서에
    연간으로만 실린다. 그래서 4분기만 빈 표가 되는데, 그 빈칸이 "그 분기에 장사를 안
    했다"로 읽힌다. 연간에서 1~3분기를 빼서 채우고 **파생값이라고 표시한다.**

    **연간과 분기의 재무제표 기준(연결/별도)이 다르면 빼지 않는다.** 다른 기준끼리
    빼면 그럴듯한데 틀린 숫자가 나온다. 그럴 때는 4분기가 그냥 빠진 채로 둔다.
    """
    by_year: dict[int, dict[int, object]] = {}
    for row in quarters:
        by_year.setdefault(row.fiscal_year, {})[row.quarter] = row

    out: list[tuple[int, int, int | None, int | None, int | None, bool]] = []
    for row in sorted(quarters, key=lambda r: (r.fiscal_year, r.quarter)):
        out.append(
            (row.fiscal_year, row.quarter, row.revenue, row.operating_income, row.net_income, False)
        )

    annual_by_year = {row.fiscal_year: row for row in annual}
    for year, found in by_year.items():
        full = annual_by_year.get(year)
        # 1~3분기가 모두 있어야 뺄 수 있다. 하나라도 비면 4분기는 낼 수 없다.
        if full is None or any(q not in found for q in (1, 2, 3)):
            continue

        def rest(name: str) -> int | None:
            total = getattr(full, name)
            if total is None:
                return None
            parts = [getattr(found[q], name) for q in (1, 2, 3)]
            if any(part is None for part in parts):
                return None
            return total - sum(parts)

        out.append(
            (year, 4, rest("revenue"), rest("operating_income"), rest("net_income"), True)
        )

    return sorted(out, key=lambda item: (item[0], item[1]))


def _section(title: str, body: str | None) -> str:
    return f"### {title}\n{body.strip()}" if body and body.strip() else ""


def _assemble(head: str, blocks: list[str], ask: str) -> str:
    # f-string 안에서 역슬래시를 쓰지 않는다. 3.12 는 받아 주지만(PEP 701) 3.11 에서는
    # 문법 오류다. 이 프로젝트는 3.11+ 를 말하고 있으므로 낮은 쪽에 맞춘다.
    # 읽는 법은 자료 **앞**에 온다. 뒤에 두었더니 "아래 수치는…" 이라고 적어 놓고
    # 정작 그 수치가 위에 있었다. 규칙은 읽기 전에 읽혀야 규칙이다.
    #
    # 결과물 규칙은 **맨 끝**이다. 무엇을 시킬지(ask)를 읽은 다음에 어떤 모양으로
    # 내놓을지를 읽는 순서라야 자연스럽다.
    kept = [block for block in blocks if block.strip()]
    return "\n\n".join([head, HEADER_RULES, *kept, ask, OUTPUT_RULES]) + "\n"


# ---------------------------------------------------------------- 국내


async def build_kr(symbol: str, preset: str = DEFAULT_PRESET) -> Prompt:
    """국내 종목 하나의 리서치 지시서."""
    spec = PRESETS.get(preset) or PRESETS[DEFAULT_PRESET]
    corp = dart_corps.get_corp(symbol)
    if corp is None:
        raise PromptError(
            f"'{symbol}' 의 DART 고유번호를 찾지 못했습니다. "
            "상장사 목록이 아직 받아지지 않았거나 비상장·상장폐지 종목일 수 있습니다."
        )

    included: list[str] = []
    missing: list[str] = []
    blocks: list[str] = []

    # 재무. 처음 보는 종목은 여기서 OpenDART 를 부르느라 몇 초 걸린다.
    fs_div = "CFS"
    try:
        fs_div, _ = await dart_financials.ensure_financials(corp.corp_code, years=ANNUAL_YEARS)
    except DartError as exc:
        logger.warning("연간 재무 적재 실패 (%s): %s", symbol, exc)
    annual = dart_financials.load(corp.corp_code, fs_div, years=ANNUAL_YEARS)

    label = FS_LABEL.get(fs_div, fs_div)
    if annual:
        included.append(f"연간 실적 {len(annual)}개년({label})")
        rows = [
            [
                str(row.fiscal_year),
                _num(row.revenue),
                _num(row.operating_income),
                _num(row.net_income),
                _num(row.total_assets),
                _num(row.total_equity),
            ]
            for row in sorted(annual, key=lambda r: r.fiscal_year)
        ]
        blocks.append(
            _section(
                f"연간 실적 ({label}재무제표 · 단위 원)",
                _table(["회계연도", "매출액", "영업이익", "당기순이익", "자산총계", "자본총계"], rows),
            )
        )
    else:
        missing.append("연간 실적")

    # 분기. 계절성과 최근 흐름은 연간만으로는 안 보인다.
    q_div = fs_div  # 적재가 실패해도 아래에서 이름이 없어 터지지 않게 미리 둔다
    try:
        q_div, _ = await dart_quarterly.ensure_quarterly(corp.corp_code, years=3)
        quarters = dart_quarterly.load(corp.corp_code, q_div, limit=QUARTER_COUNT)
    except DartError as exc:
        logger.warning("분기 재무 적재 실패 (%s): %s", symbol, exc)
        quarters = []
    if quarters:
        points = _with_q4(quarters, annual if q_div == fs_div else [])
        included.append(f"분기 실적 {len(points)}개")
        rows = [
            [
                f"{year} {quarter}Q" + (" (파생)" if derived else ""),
                _num(revenue),
                _num(operating),
                _num(net),
            ]
            for year, quarter, revenue, operating, net, derived in points
        ]
        blocks.append(
            _section(
                "분기 실적 (해당 분기 3개월 · 단위 원)",
                _table(["기간", "매출액", "영업이익", "당기순이익"], rows)
                + "\n\n※ **(파생)** 표시는 DART 에 4분기 보고서가 없어 연간에서 1~3분기를"
                " 뺀 값입니다. 공시에 그대로 적힌 숫자가 아니므로 그렇게 밝혀 둡니다.",
            )
        )
    else:
        missing.append("분기 실적")

    # 시세·밸류에이션.
    value = valuation_service.compute(symbol, corp.corp_code, fs_div, label)
    if value is not None:
        included.append("현재가·밸류에이션")
        blocks.append(
            _section(
                "시세와 밸류에이션",
                _table(
                    ["항목", "값"],
                    [
                        ["주가", f"{value.price:,}원 ({value.price_label})"],
                        ["시가총액", f"{value.market_cap:,}원"],
                        ["상장주식수", f"{value.listed_shares:,}주"],
                        ["PER", f"{value.per}배" if value.per else "—"],
                        ["PBR", f"{value.pbr}배" if value.pbr else "—"],
                        ["배당수익률", _pct(value.dividend_yield)],
                        ["EPS", _num(value.eps)],
                        ["BPS", _num(value.bps)],
                    ],
                ),
            )
        )
    else:
        missing.append("밸류에이션")

    # 공시 목록. **이게 이 지시서의 핵심이다** — 받는 쪽이 열어서 읽을 원문이다.
    #
    # **정기보고서를 따로 받는다.** 최근순으로만 채웠더니 사업보고서(3월 접수)가 15칸
    # 밖으로 밀려났다. 기업 분석에서 가장 먼저 읽어야 할 문서가 목록에 없는 셈이라,
    # 유형 A(정기공시)로 한 번 더 불러 자리를 따로 마련한다. 호출 하나가 더 드는 값어치가 있다.
    periodic: list = []
    recent: list = []
    try:
        end = today_kst()
        begin = end - timedelta(days=PERIODIC_DAYS)
        async with DartClient() as dart:
            periodic = await dart.get_disclosures(
                corp.corp_code,
                begin=begin,
                end=end,
                count=PERIODIC_COUNT,
                final_only=True,
                report_type="A",
            )
            recent = await dart.get_disclosures(
                corp.corp_code,
                begin=end - timedelta(days=DISCLOSURE_DAYS),
                end=end,
                count=DISCLOSURE_FETCH,
                final_only=True,
            )
    except (DartError, RuntimeError) as exc:
        logger.warning("공시 목록 조회 실패 (%s): %s", symbol, exc)

    def _rows(items: list) -> list[list[str]]:
        return [
            [item.received_date, item.report_name.replace("|", "／"), item.viewer_url]
            for item in items
        ]

    if periodic:
        included.append(f"정기보고서 {len(periodic)}건")
        blocks.append(
            _section(
                "정기보고서 — **여기부터 읽으십시오** (원문 링크)",
                _table(["접수일", "보고서명", "원문"], _rows(periodic)),
            )
        )
    else:
        missing.append("정기보고서")

    # 정기보고서와 겹치는 것은 아래 표에서 뺀다. 같은 줄이 두 번 나오면 목록이 지저분하다.
    taken = {item.receipt_no for item in periodic}
    others = _dedupe_by_name(
        [item for item in recent if item.receipt_no not in taken], DISCLOSURE_COUNT
    )
    if others:
        included.append(f"그 밖의 공시 {len(others)}건")
        blocks.append(
            _section(
                f"그 밖의 최근 {DISCLOSURE_DAYS // 30}개월 공시 (원문 링크)",
                _table(["접수일", "보고서명", "원문"], _rows(others)),
            )
        )
    elif not periodic:
        missing.append("공시 목록")

    head = "\n".join(
        [
            f"# {corp.corp_name} ({symbol}) — 기업 분석 요청",
            "",
            "당신은 국내 상장사를 분석하는 애널리스트입니다. 읽는 사람은 투자와 공시에",
            "지식이 깊은 금융권 실무자입니다.",
            "",
            f"아래는 **{today_kst().isoformat()} 기준** 공시 원자료에서 계산한 확정 자료입니다.",
            "해석은 들어 있지 않습니다.",
        ]
    )
    return Prompt(
        symbol=symbol,
        name=corp.corp_name,
        market="KR",
        preset=preset if preset in PRESETS else DEFAULT_PRESET,
        text=_assemble(head, blocks, spec["ask"]),
        included=included,
        missing=missing,
    )


# ---------------------------------------------------------------- 미국


async def build_us(ticker: str, preset: str = DEFAULT_PRESET) -> Prompt:
    """미국 종목 하나의 리서치 지시서."""
    spec = PRESETS.get(preset) or PRESETS[DEFAULT_PRESET]
    ticker = ticker.strip().upper()
    company = sec_companies.get_company(ticker)
    if company is None:
        raise PromptError(
            f"'{ticker}' 의 CIK 를 찾지 못했습니다. SEC 상장사 목록에 없는 티커일 수 있습니다."
        )

    included: list[str] = []
    missing: list[str] = []
    blocks: list[str] = []

    try:
        await sec_financials.ensure_financials(company.cik, years=ANNUAL_YEARS)
    except SecError as exc:
        logger.warning("미국 연간 재무 적재 실패 (%s): %s", ticker, exc)
    annual = sec_financials.load(company.cik, years=ANNUAL_YEARS)

    if annual:
        included.append(f"연간 실적 {len(annual)}개년")
        rows = [
            [
                f"FY{row.fiscal_year}",
                row.period_end,
                _num(row.revenue),
                _num(row.operating_income),
                _num(row.net_income),
                _num(row.total_assets),
                _num(row.total_equity),
            ]
            for row in sorted(annual, key=lambda r: r.fiscal_year)
        ]
        blocks.append(
            _section(
                "연간 실적 (SEC XBRL · 단위 USD)",
                _table(
                    ["회계연도", "결산일", "매출", "영업이익", "순이익", "자산총계", "자본총계"],
                    rows,
                )
                # 회계연도 이름은 회사마다 부르는 법이 다르다. 우리는 결산일에서 규칙으로
                # 붙이므로 회사가 부르는 이름과 어긋날 수 있다 — NVIDIA 의 1월 결산이
                # 그렇다(우리 FY2025 = 회사의 fiscal 2026). 첫 실사용에서 받는 쪽이
                # 이걸 한 문단 써서 바로잡았다. 미리 밝혀 두면 그 품이 들지 않는다.
                + "\n\n※ **회계연도 이름은 결산일에서 우리가 붙인 것**이라 회사가 스스로"
                " 부르는 이름과 한 해 어긋날 수 있습니다(1월 결산 회사가 특히 그렇습니다)."
                " **결산일을 기준으로 읽으시고**, 회사 표기를 쓸 때는 그 사실을 밝혀 주십시오.",
            )
        )
    else:
        missing.append("연간 실적")

    value = valuation_service.compute_us(ticker)
    if value is not None:
        included.append("현재가·밸류에이션")
        blocks.append(
            _section(
                "시세와 밸류에이션",
                _table(
                    ["항목", "값"],
                    [
                        ["주가", f"${value.price}"],
                        ["시가총액", f"${value.market_cap:,}" if value.market_cap else "—"],
                        ["PER", f"{value.per}배" if value.per else "—"],
                        ["PBR", f"{value.pbr}배" if value.pbr else "—"],
                        ["배당수익률", _pct(value.dividend_yield)],
                    ],
                ),
            )
        )
    else:
        missing.append("밸류에이션")

    # 공시 목록. 국내와 같은 이유로 **정기보고서를 따로 올린다** — 최근순으로만 채우면
    # 8-K 가 자리를 먹고 10-K 가 밀려난다. 미국은 한 번 받은 목록을 걸러 쓰면 되므로
    # 국내처럼 호출을 더 하지는 않는다(SEC 는 제출 이력 전체를 한 번에 준다).
    periodic: list[UsFiling] = []
    others: list[UsFiling] = []
    try:
        async with SecClient() as sec:
            submissions = await sec.get_submissions(company.cik)
        periodic = SecClient.parse_filings(
            submissions, forms=("10-K", "10-Q", "20-F", "40-F"), limit=PERIODIC_COUNT
        )
        taken = {f.accession_no for f in periodic}
        others = [
            f
            for f in SecClient.parse_filings(submissions, forms=None, limit=DISCLOSURE_FETCH)
            if f.accession_no not in taken
        ][:DISCLOSURE_COUNT]
    except SecError as exc:
        logger.warning("미국 공시 목록 조회 실패 (%s): %s", ticker, exc)

    def _rows(items: list[UsFiling]) -> list[list[str]]:
        return [[f.filing_date, f.form.replace("|", "／"), f.viewer_url] for f in items]

    if periodic:
        included.append(f"정기보고서 {len(periodic)}건")
        blocks.append(
            _section(
                "정기보고서 (10-K·10-Q) — **여기부터 읽으십시오**",
                _table(["제출일", "양식", "원문"], _rows(periodic)),
            )
        )
    else:
        missing.append("정기보고서")

    if others:
        included.append(f"그 밖의 공시 {len(others)}건")
        blocks.append(
            _section("그 밖의 최근 공시 (원문 링크)", _table(["제출일", "양식", "원문"], _rows(others)))
        )
    elif not periodic:
        missing.append("공시 목록")

    industry = company.sic_description or "—"
    head = "\n".join(
        [
            f"# {company.name} ({ticker}) — 기업 분석 요청",
            "",
            "당신은 미국 상장사를 분석해 한국의 금융 실무자에게 설명하는 애널리스트입니다.",
            "**한국어로 쓰되 회사명·제품명·부문명은 원문 표기를 유지**하십시오.",
            "",
            f"업종(SIC): {industry} · CIK: {company.cik}",
            "",
            f"아래는 **{today_kst().isoformat()} 기준** SEC 원자료에서 계산한 확정 자료입니다.",
            "해석은 들어 있지 않습니다.",
        ]
    )
    return Prompt(
        symbol=ticker,
        name=company.name,
        market="US",
        preset=preset if preset in PRESETS else DEFAULT_PRESET,
        text=_assemble(head, blocks, spec["ask"]),
        included=included,
        missing=missing,
    )
