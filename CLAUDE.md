# CLAUDE.md

이 파일은 클로드 코드가 매 세션 자동으로 읽는 프로젝트 규칙 파일이다. 프로젝트 루트에 둔다.

---

## 프로젝트

국내(KRX)와 미국 주식의 시세·공시·재무·기업분석을 한 화면에서 보는 **읽기 전용 정보 대시보드**를 만든다. 개인과 지인 소수가 보며, 완성 후 입사지원 포트폴리오로 링크를 공개한다.

상세 기획은 같은 폴더의 `기획서.md`를 참고한다. 이 파일과 기획서가 충돌하면 이 파일이 우선한다.

## 협업자에 대해

이 프로젝트의 사용자는 **개발 경험이 없는 금융권 실무자**다. 투자와 공시·재무 데이터에 대한 도메인 지식은 깊지만, 프로그래밍 언어나 프레임워크는 모른다. 따라서:

- 전문 용어를 쓸 때는 한 줄 설명을 붙인다.
- 사용자가 직접 해야 할 일(키 발급, 사이트 가입, 설정 변경, 명령어 실행)은 **화면에서 클릭할 위치까지 구체적으로** 안내한다.
- 사용자에게 코드 수정을 요구하지 않는다. 코드는 전부 클로드 코드가 작성하고, 사용자는 실행 결과를 확인하고 판단한다.
- 선택지가 있으면 추천안을 제시하고 이유를 설명한 뒤 확인을 받는다. "어떻게 할까요?"만 묻지 않는다.

## 진행 원칙

**한 번에 하나씩 만든다.** 여러 기능을 동시에 구현하지 않는다. 하나가 실제로 동작하는 것을 사용자가 눈으로 확인한 뒤 다음으로 넘어간다.

**필요한 것은 먼저 요구한다.** API 키, 계정, 결정이 필요하면 코드를 짜기 전에 멈추고 사용자에게 요청한다. 임의의 더미 값으로 진행하고 나중에 바꾸게 하지 않는다.

**사용자의 준비 작업도 안내 대상이다.** 계정 가입, 키 발급, 사이트 설정, 프로그램 설치처럼 사용자가 직접 해야 하는 일도 클로드 코드가 시점을 판단해 안내한다. 사용자가 미리 준비해 올 것이라고 가정하지 않는다. 요구할 때는 한 번에 하나씩, 어느 사이트의 어느 메뉴인지까지 구체적으로 알려주고, 완료 확인을 받은 뒤 다음으로 넘어간다. 프로젝트 루트의 `TODO.md`에 사용자가 해야 할 일 목록을 유지하고 진행에 따라 갱신한다.

**추측하지 않는다.** 외부 API 스펙이 불확실하면 아래 문서 URL을 직접 읽는다. 기억에 의존해 엔드포인트나 필드명을 지어내지 않는다.

**작업 후 반드시 실행해서 확인한다.** 코드를 작성했으면 실제로 돌려보고 결과를 사용자에게 보여준다. "이렇게 하면 됩니다"로 끝내지 않는다.

**단계마다 커밋한다.** 동작이 확인되면 의미 있는 커밋 메시지로 커밋한다. 되돌릴 지점을 남기는 것이 중요하다.

**막히면 알린다.** 세 번 시도해도 안 되면 우회하지 말고 상황을 설명하고 사용자와 상의한다.

## 절대 규칙

1. **키는 `.env`에만.** `client_id`, `client_secret`, OpenDART 인증키, Anthropic API 키를 코드에 하드코딩하지 않는다. `.gitignore`에 `.env`가 있는지 매번 확인한다. 커밋 전 키가 섞여 있지 않은지 점검한다.

2. **계좌·자산·주문 API는 쓰지 않는다.** 토스증권 API 중 `/api/v1/accounts`, `/api/v1/holdings`, `/api/v1/orders`, `/api/v1/conditional-orders`, `/api/v1/buying-power`, `/api/v1/sellable-quantity` 계열은 이 프로젝트 범위 밖이다. 사용자가 요청해도 이유를 설명하고 재확인한다. `X-Tossinvest-Account` 헤더는 필요 없다.

3. **숫자는 LLM에게 시키지 않는다.** 매출·이익·마진·비율 등 모든 재무 수치는 XBRL 데이터에서 직접 계산한다. LLM은 서술형 해석만 담당한다. LLM이 문서에서 숫자를 읽어 요약하게 만들지 않는다.

4. **브라우저에서 외부 API를 직접 호출하지 않는다.** 모든 외부 호출은 백엔드에서만 나간다. 토스증권은 허용 IP 방식이라 애초에 브라우저에서 막히고, 시크릿이 노출된다.

5. **rate limit을 지킨다.** API 그룹별 토큰 버킷을 두고 그 뒤에서만 호출한다. 429를 받으면 `Retry-After`를 지키고 지수 백오프를 적용한다.

6. **브라우저 저장소를 쓰지 않는다.** localStorage/sessionStorage 대신 서버 DB 또는 React 상태를 쓴다.

## 기술 스택

- 백엔드: Python 3.11+ / FastAPI
- DB: SQLite (SQLAlchemy)
- 프론트엔드: React + Vite + TailwindCSS
- 차트: lightweight-charts 또는 ECharts
- 배포: 소형 VPS 상시 구동, Caddy로 HTTPS
- 스케줄러: APScheduler 또는 cron

새 라이브러리를 추가할 때는 이유를 설명하고 확인을 받는다.

## 디렉터리 구조

```
/backend
  /app
    main.py            FastAPI 진입점
    config.py          환경변수 로드
    /clients           외부 API 클라이언트 (toss.py, dart.py, edgar.py, ecos.py)
    /services          비즈니스 로직 (시세 폴러, 분석 파이프라인)
    /models            DB 모델
    /routers           API 엔드포인트
  /scripts             일회성/배치 스크립트
/frontend
  /src
    /pages /components /lib
/data                  SQLite 파일, 캐시 (gitignore)
.env                   키 (gitignore)
CLAUDE.md
기획서.md
```

## 외부 데이터 소스 — 스펙은 반드시 원문 확인

**토스증권 Open API** (국내·미국 시세, 종목정보, 수급, 환율, 장 운영시간, 랭킹, 지수)
- LLM용 안내: https://developers.tossinvest.com/llms.txt
- 개요·rate limit·에러: https://openapi.tossinvest.com/openapi-docs/overview.md
- OpenAPI JSON (스펙의 최종 근거): https://openapi.tossinvest.com/openapi-docs/latest/openapi.json
- Base: `https://openapi.tossinvest.com`, 인증은 OAuth 2.0 Client Credentials
- 웹소켓 스펙의 최종 근거는 AsyncAPI JSON: https://openapi.tossinvest.com/openapi-docs/latest/asyncapi.json
- **현재가는 웹소켓으로 받는다** (`clients/toss_ws.py`, 2026-08-24 도입).
  `wss://openapi-ws.tossinvest.com/ws/v1` · 구독은 선언형 full-replace · 텍스트 `PING` 60초.
  **REST 폴링을 걷어내지 않았다.** 구독 직후엔 값이 안 오고, 구독은 100종목까지이며,
  푸시는 LOSSY 라 유실을 감지할 수 없다. 폴링이 첫 값·초과분·유실을 메우는 안전망으로 남는다.
- **동시 연결은 계정당 2개다.** 배포 서버 하나 + 개발 PC 하나면 꽉 찬다. 셋째를 열면 가장
  오래된 연결이 소리 없이 끊긴다. 로컬에서 시험할 때 배포 서버의 실시간이 끊길 수 있다.
- 주의: 허용 IP에 등록되지 않은 IP에서의 호출은 403으로 차단된다. 개발은 사용자의 집에서 이루어지므로 집 IP가 등록되어 있어야 하고, 가정용 회선은 IP가 바뀔 수 있다. 원인 불명의 403이 발생하면 이것부터 확인하도록 안내한다.

**OpenDART** (국내 공시·재무) — https://opendart.fss.or.kr/intro/main.do

**SEC EDGAR** (미국 공시·재무) — https://www.sec.gov/about/developer-resources
- `company_tickers.json`으로 티커→CIK 매핑, CIK는 10자리 zero-padding
- `https://data.sec.gov/submissions/CIK##########.json` — 공시 이력
- `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` — XBRL 전체
- `https://data.sec.gov/api/xbrl/frames/us-gaap/{CONCEPT}/{UNIT}/CY{YEAR}.json` — 횡단면
- **필수**: User-Agent 헤더에 이름과 이메일. 없으면 403.
- **필수**: 초당 10건 이하. 실무적으로 8 req/s에 100ms 지연. 차단 시 즉시 재시도하면 차단이 길어진다.
- 대량 적재는 개별 호출 대신 `sec.gov/files/`의 벌크 파일 사용.

**한국은행 ECOS / FRED** (매크로 지표)

**Anthropic API** (10-K 서술 분석) — https://platform.claude.com/docs/en/about-claude/pricing
- 배치 작업은 Batch API(50% 할인)를 쓴다.
- 모델은 기본 Haiku, 품질이 필요한 건만 상위 모델로 라우팅한다.

## 용어

- **10-K**: 미국 상장사의 연차보고서. Item 1(사업), 1A(위험요인), 7(MD&A)이 분석 핵심.
- **XBRL**: 재무 항목을 기계가 읽도록 태깅한 표준 형식.
- **CIK**: SEC가 공시 제출자에게 부여한 고유 번호. 티커가 아니라 이걸로 조회한다.
- **폴링**: 서버가 주기적으로 API를 호출해 최신값을 가져오는 방식.
- **rate limit**: 초당 허용 호출 수 상한.
