// 백엔드 호출과 응답 타입.
//
// 백엔드는 등락률·현재가 같은 값을 **문자열**로 내려준다. 소수 계산 오차를 막으려고
// 서버에서 Decimal 로 다루기 때문이다. 화면에 그릴 때만 숫자로 바꾼다.

export type Quote = {
  trade_date: string
  symbol: string
  name: string
  market: 'KOSPI' | 'KOSDAQ' | 'KONEX'
  close: number
  change: number
  change_rate: string
  open: number
  high: number
  low: number
  volume: number
  trade_value: number
  market_cap: number
}

export type PricePoint = {
  trade_date: string
  close: number
  open: number
  high: number
  low: number
  volume: number
  change_rate: string
}

export type CollectionStatus = {
  next_run_at: string | null
  running: boolean
  last_run_at: string | null
  last_run_ok: boolean | null
  last_run_days: number
  last_run_rows: number
  last_error: string | null
}

export type DataStatus = {
  collection: CollectionStatus
  latest_trade_date: string | null
  oldest_trade_date: string | null
  trading_days: number
  symbols_on_latest: number
  total_rows: number
  source: string
  note: string
}

export type MarketPhase =
  | 'PRE'
  | 'REGULAR'
  | 'AFTER'
  | 'DAY'
  | 'CLOSED'
  | 'HOLIDAY'
  | 'UNKNOWN'

/** 국내와 미국은 장 시간이 달라 상태를 따로 본다. */
export type Country = 'KR' | 'US'

export type MarketState = {
  phase: MarketPhase
  label: string
  trade_date: string | null
  next_open: string | null
  session_end: string | null
  is_live: boolean
}

export type LiveQuote = {
  symbol: string
  last_price: string
  base_price: string | null
  base_date: string | null
  change: string | null
  change_rate: string | null
  timestamp: string | null
  age_seconds: number
  stale: boolean
}

export type PricesResponse = {
  markets: Record<Country, MarketState>
  prices: LiveQuote[]
  missing: string[]
  error: string | null
  last_success_at: string | null
  /** 전부 웹소켓 체결 푸시로 들어오고 있는가. 거짓이면 폴링으로 받는 중이다. */
  realtime: boolean
}

export type SortKey = 'market_cap' | 'trade_value' | 'volume' | 'change_rate' | 'close'
export type MarketFilter = 'KOSPI' | 'KOSDAQ' | 'KONEX'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    // 2026-09-01 부터 **보는 것은 누구나, 바꾸는 것은 주인만**이다(`deploy/Caddyfile`).
    // 방문자가 메모를 쓰거나 분석 버튼을 누르면 여기로 온다. "HTTP 401" 이라고만 뜨면
    // 고장으로 읽히므로 무슨 일인지 적는다. 이 응답은 Caddy 가 내므로 detail 이 없다.
    if (response.status === 401) {
      throw new Error('이 기능은 사이트 주인만 쓸 수 있습니다. 보는 것은 누구나 됩니다.')
    }

    // 백엔드는 실패 이유를 detail 에 한국어로 담아 보낸다. 그대로 화면에 보여준다.
    let detail = `요청이 실패했습니다 (HTTP ${response.status})`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // 응답이 JSON 이 아니면 기본 메시지를 쓴다.
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

function get<T>(path: string): Promise<T> {
  return request<T>(path)
}

export function fetchStatus() {
  return get<DataStatus>('/api/meta')
}

export function fetchStocks(options: {
  sort: SortKey
  market: MarketFilter | null
  limit: number
}) {
  const params = new URLSearchParams({
    sort: options.sort,
    limit: String(options.limit),
  })
  if (options.market) params.set('market', options.market)
  return get<Quote[]>(`/api/stocks?${params}`)
}

export function searchStocks(keyword: string) {
  return get<Quote[]>(`/api/stocks/search?q=${encodeURIComponent(keyword)}`)
}

/** 종목의 가장 최근 확정 시세. 현재가는 fetchLivePrices 가 따로 준다. */
export function fetchStockDetail(symbol: string) {
  return get<Quote>(`/api/stocks/${symbol}`)
}

export function fetchDailyPrices(symbol: string, days = 90) {
  return get<PricePoint[]>(`/api/stocks/${symbol}/daily?days=${days}`)
}

export type FinancialYear = {
  fiscal_year: number
  revenue: number | null
  gross_profit: number | null
  operating_income: number | null
  net_income: number | null
  total_assets: number | null
  total_liabilities: number | null
  total_equity: number | null
  operating_margin: string | null
  net_margin: string | null
  revenue_growth: string | null
  operating_income_growth: string | null
  roe: string | null
  debt_ratio: string | null
  receipt_no: string
  source_url: string
}

export type FinancialsResponse = {
  stock_code: string
  corp_name: string
  corp_code: string
  fs_div: string
  fs_label: string
  currency: string
  years: FinancialYear[]
}

/** 연간 재무. 처음 보는 종목은 OpenDART 를 부르느라 몇 초 걸릴 수 있다. */
export function fetchFinancials(symbol: string, years = 6) {
  return get<FinancialsResponse>(`/api/stocks/${symbol}/financials?years=${years}`)
}

/**
 * 한 분기의 재무. **두 기준을 함께 담는다** — 당분기 3개월(`revenue`)과
 * 연초부터 누적(`revenue_cum`). 둘 다 보고서에 적힌 원값이라 화면에서 어느 쪽을
 * 골라도 계산한 숫자가 아니다.
 */
export type QuarterPoint = {
  fiscal_year: number
  quarter: number
  label: string
  /** 4분기의 3개월 손익만 참 — DART 에 4분기 보고서가 없어 연간에서 빼서 구한다. */
  derived: boolean

  revenue: number | null
  gross_profit: number | null
  operating_income: number | null
  net_income: number | null

  revenue_cum: number | null
  gross_profit_cum: number | null
  operating_income_cum: number | null
  net_income_cum: number | null

  /** 분기말 잔액. 누적이라는 개념이 없다. */
  total_assets: number | null
  total_liabilities: number | null
  total_equity: number | null

  operating_margin: string | null
  net_margin: string | null
  operating_margin_cum: string | null
  net_margin_cum: string | null
  /** 부채총계/자본총계. 둘 다 분기말 잔액이라 분기에도 성립한다. ROE 는 내지 않는다. */
  debt_ratio: string | null

  /** 전분기가 아니라 **전년 동분기** 대비다. 분기 실적은 계절을 심하게 탄다. */
  revenue_yoy: string | null
  operating_income_yoy: string | null
  revenue_cum_yoy: string | null
  operating_income_cum_yoy: string | null

  receipt_no: string
  source_url: string
}

export type QuarterlyResponse = {
  stock_code: string
  corp_name: string
  corp_code: string
  fs_div: string
  fs_label: string
  currency: string
  quarters: QuarterPoint[]
}

/**
 * 밸류에이션. **저장하지 않고 그때그때 계산해서 온다** — 주가가 계속 바뀌기 때문이다.
 *
 * 비율은 문자열로 온다(서버가 소수 둘째 자리로 고정한 Decimal). 화면에서 다시 숫자로
 * 바꿔 계산하지 않는다.
 */
export type Valuation = {
  stock_code: string
  corp_name: string

  price: number
  price_label: string
  listed_shares: number
  market_cap: number

  fiscal_year: number | null
  fs_label: string | null
  /** 지배주주 몫으로 냈는가. 별도재무제표에는 비지배지분이 없어 거짓이다. */
  owners_basis: boolean

  eps: number | null
  bps: number | null
  dps: number | null
  dps_year: number | null

  per: string | null
  pbr: string | null
  dividend_yield: string | null

  /** 값이 없을 때 그 사정. 화면은 "—" 대신 이 문장을 보여준다. */
  per_note: string | null
  pbr_note: string | null
  dividend_note: string | null
}

export function fetchValuation(symbol: string) {
  return get<Valuation>(`/api/stocks/${symbol}/valuation`)
}

/** 분기·반기 재무. 처음 보는 종목은 분기마다 한 번씩 부르느라 십여 초 걸린다. */
export function fetchQuarterlyFinancials(symbol: string, quarters = 12) {
  return get<QuarterlyResponse>(
    `/api/stocks/${symbol}/financials/quarterly?quarters=${quarters}`,
  )
}

// ── 미국 주식 (SEC EDGAR + 토스 시세) ──────────────────────────────

export type UsListItem = {
  symbol: string
  name: string
  english_name: string | null
  market: string | null
  security_type: string | null
  last_price: string
  base_price: string
  change: string
  change_rate: string
  trading_volume: number
  trading_amount: number
  currency: string
}

export type UsCompanyDetail = {
  ticker: string
  cik: string
  name: string
  exchange: string | null
  industry: string | null
  fiscal_year_end: string | null
  website: string | null
}

export type UsFinancialYear = {
  fiscal_year: number
  period_end: string
  revenue: number | null
  gross_profit: number | null
  operating_income: number | null
  net_income: number | null
  total_assets: number | null
  total_liabilities: number | null
  total_equity: number | null
  operating_margin: string | null
  net_margin: string | null
  revenue_growth: string | null
  roe: string | null
  debt_ratio: string | null
  accession_no: string
  filed_date: string
  source_url: string
}

export type UsFinancialsResponse = {
  ticker: string
  cik: string
  name: string
  currency: string
  years: UsFinancialYear[]
}

export type UsFilingItem = {
  accession_no: string
  form: string
  filing_date: string
  report_date: string
  description: string
  viewer_url: string
}

/**
 * 미국 종목 목록.
 *
 * **정렬을 바꾸면 줄 순서가 아니라 종목이 바뀐다.** 국내는 전 종목 시세를 DB 에
 * 들고 있어 같은 종목을 다시 줄 세우지만, 미국은 목록의 출처가 토스 랭킹이라
 * "거래대금 상위 100"과 "거래량 상위 100"이 애초에 다른 100개다.
 */
export type UsSort = 'trade_value' | 'volume' | 'gainers' | 'losers'

export function fetchUsList(limit = 50, sort: UsSort = 'trade_value') {
  return get<UsListItem[]>(`/api/us/list?limit=${limit}&sort=${sort}`)
}

/** 검색은 SEC 티커 목록에서 찾는다. 시세가 아니라 회사 식별 정보만 돌아온다. */
export function searchUsStocks(keyword: string) {
  return get<{ ticker: string; cik: string; name: string }[]>(
    `/api/us/search?q=${encodeURIComponent(keyword)}`,
  )
}

export function fetchUsCompany(ticker: string) {
  return get<UsCompanyDetail>(`/api/us/${encodeURIComponent(ticker)}`)
}

export function fetchUsFinancials(ticker: string, years = 6) {
  return get<UsFinancialsResponse>(`/api/us/${encodeURIComponent(ticker)}/financials?years=${years}`)
}

export function fetchUsFilings(ticker: string, count = 15) {
  return get<UsFilingItem[]>(`/api/us/${encodeURIComponent(ticker)}/filings?count=${count}`)
}

// ── 10-K 서술 분석 (Anthropic) ─────────────────────────────────────
//
// 조회(GET)는 저장된 것만 읽으므로 공짜다. 실행(POST)만 돈이 든다. 화면은 이 구분을
// 그대로 따른다 — 상세를 열면 GET 만 나가고, POST 는 사용자가 버튼을 눌러야 나간다.

export type UsRiskItem = {
  title: string
  why_it_matters: string
  /** 모든 보고서에 붙는 형식적 위험이면 true */
  is_boilerplate: boolean
}

/** 사업 부문 하나. 이름과 설명이 갈려 있어야 화면이 카드로 그린다. */
export type AnalysisSegment = {
  name: string
  what: string
}

export type UsAnalysis = {
  /** ok=분석 있음 / none=아직 안 함 / pending=배치에 맡겨 둔 중 / failed=실패 */
  status: 'ok' | 'none' | 'pending' | 'failed'
  ticker: string
  fiscal_year: number | null
  period_end: string | null
  filed_date: string | null
  source_url: string | null
  model: string | null
  generated_at: string | null
  sections: string[]
  truncated: string[]
  /** 이 회사가 뭘로 돈을 버는지 한 문장. 카드 맨 위에 크게 놓인다. */
  one_liner: string | null
  business_summary: string | null
  segments: AnalysisSegment[]
  key_risks: UsRiskItem[]
  mdna_points: string[]
  moat_and_competition: string | null
  /** 이 보고서만으로 답이 안 나온 것. 빈칸을 밝히는 쪽이 정직하다. */
  open_questions: string[]
  error: string | null
}

/** 저장된 분석 조회. 새로 분석하지 않으므로 비용이 들지 않는다. */
export function fetchUsAnalysis(ticker: string) {
  return get<UsAnalysis>(`/api/us/${encodeURIComponent(ticker)}/analysis`)
}

/** 분석 실행. 30초~2분 걸리고 문서 한 건당 비용이 발생한다. */
export function runUsAnalysis(ticker: string, force = false) {
  const query = force ? '?force=true' : ''
  return request<UsAnalysis>(`/api/us/${encodeURIComponent(ticker)}/analysis${query}`, {
    method: 'POST',
  })
}

// ── 매크로 스트립 ──────────────────────────────────────────────────
//
// 값은 서버에서 이미 반올림·쉼표까지 넣은 **문자열**로 온다. 지표마다 표기 자리수가
// 다르고(환율 1자리, 지수 2자리, 금리 2자리) 그 판단이 서버에 있어서다.
// 화면에서 다시 숫자로 바꿔 계산하지 않는다.

export type MacroItem = {
  code: string
  label: string
  /** 화면에 그대로 쓸 문자열 */
  value: string
  /** '' | '원' | '%' | '$' */
  unit: string
  /** 등락률(%). 없는 지표는 null */
  change_rate: string | null
  /** 기준 시각 또는 기준일. 빈 문자열이면 표시하지 않는다 */
  as_of: string
  source: string
  /** 화면에 함께 밝혀야 하는 단서 (예: SPY 는 지수가 아님) */
  note: string
  /** 지금 못 받아 저장된 값을 보여주는 중 */
  stale: boolean
}

export type MacroStrip = {
  items: MacroItem[]
  /** 못 받은 지표의 이유. 비어 있으면 전부 정상 */
  errors: string[]
}

export function fetchMacro() {
  return get<MacroStrip>('/api/macro')
}

// ── 수급 동향 (국내 전용) ───────────────────────────────────────────
//
// 순매수는 **주(수량)** 단위 정수다. 금액이 아니다 — 토스 종목별 엔드포인트가 수량만 준다.
// 지표(`metrics`)는 자료마다 갱신 시각이 달라 **항목별로 기준일이 다를 수 있다.**

export type InvestorDay = {
  date: string
  /** 개인 순매수 (주). 자료가 없으면 null */
  individual: number | null
  foreigner: number | null
  institution: number | null
}

export type FlowMetric = {
  label: string
  /** 화면에 그대로 쓸 문자열 */
  value: string
  unit: string
  /** 이 지표의 기준일 */
  as_of: string
  note: string
}

export type Flows = {
  symbol: string
  /** 최신 거래일부터 */
  investors: InvestorDay[]
  metrics: FlowMetric[]
  /** 못 받은 자료의 이유. 비어 있으면 전부 정상 */
  errors: string[]
}

export function fetchFlows(symbol: string, days = 5) {
  return get<Flows>(`/api/stocks/${symbol}/flows?days=${days}`)
}

// ── 국내 사업보고서 서술 분석 ───────────────────────────────────────
//
// 미국 10-K 분석과 같은 규칙이다 — GET 은 저장된 것만 읽어 공짜, POST 만 돈이 든다.
//
// 응답 모양이 미국과 조금 다르다. 국내 사업보고서에는 위험요인 전용 항목이 없어
// 보고서 곳곳에서 찾아내야 하므로, 각 위험이 어디서 나왔는지 `source` 로 밝힌다.

export type KrRiskItem = {
  title: string
  why_it_matters: string
  /** 보고서 어느 절에서 나온 내용인지 */
  source: string
}

export type KrAnalysis = {
  /** ok=분석 있음 / none=아직 안 함 / pending=배치에 맡겨 둔 중 / failed=실패 */
  status: 'ok' | 'none' | 'pending' | 'failed'
  stock_code: string
  corp_name: string | null
  report_name: string | null
  fiscal_year: number | null
  received_date: string | null
  source_url: string | null
  model: string | null
  generated_at: string | null
  sections: string[]
  truncated: string[]
  /** 이 회사가 뭘로 돈을 버는지 한 문장. 카드 맨 위에 크게 놓인다. */
  one_liner: string | null
  business_summary: string | null
  segments: AnalysisSegment[]
  key_risks: KrRiskItem[]
  mdna_points: string[]
  moat_and_competition: string | null
  /** 이 보고서만으로 답이 안 나온 것. 빈칸을 밝히는 쪽이 정직하다. */
  open_questions: string[]
  error: string | null
}

/** 저장된 분석 조회. 새로 분석하지 않으므로 비용이 들지 않는다. */
export function fetchKrAnalysis(symbol: string) {
  return get<KrAnalysis>(`/api/stocks/${symbol}/analysis`)
}

/** 분석 실행. 원문이 수 MB 라 1~3분 걸리고 보고서 한 건당 비용이 발생한다. */
export function runKrAnalysis(symbol: string, force = false) {
  const query = force ? '?force=true' : ''
  return request<KrAnalysis>(`/api/stocks/${symbol}/analysis${query}`, { method: 'POST' })
}

// ── 종목 메모 ────────────────────────────────────
//
// 기획서가 "이 프로젝트의 차별점" 이라 부른 기능이다. 서버 DB 에 저장되므로 브라우저를
// 지워도 남고, 매일 백업에도 함께 들어간다.
//
// 시각은 UTC 오프셋이 붙은 문자열로 온다. 그래야 화면이 지역 시각으로 바꿔 보여줄 수 있다.

export type Note = {
  id: number
  symbol: string
  market: string
  body: string
  tags: string[]
  created_at: string
  updated_at: string
  /** 작성 뒤에 고친 적이 있는가 */
  edited: boolean
}

export function fetchNotes(symbol: string, limit = 50) {
  return get<Note[]>(`/api/notes?symbol=${encodeURIComponent(symbol)}&limit=${limit}`)
}

export function createNote(symbol: string, body: string, tags: string[] = []) {
  return request<Note>('/api/notes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, body, tags }),
  })
}

export function updateNote(id: number, body: string, tags: string[] = []) {
  return request<Note>(`/api/notes/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ body, tags }),
  })
}

export function deleteNote(id: number) {
  return request<{ removed: boolean }>(`/api/notes/${id}`, { method: 'DELETE' })
}

// ── 가동 상태 ───────────────────────────────────────────────────────
//
// 앱이 스스로 판단한 상태다. `/health` 는 살아 있는지만 답하고, 이쪽은 무엇이 어떻게
// 고장났는지까지 답한다. 서버의 감시 스크립트도 같은 응답을 읽는다 — 화면과 알림이
// 어긋나지 않게 하려는 것이다.

export type HealthCheck = {
  name: string
  /** 'ok' | 'degraded' | 'down' */
  status: string
  detail: string
}

export type HealthDetail = {
  status: string
  /** 문제를 한 줄로 요약한 것 */
  summary: string
  uptime_seconds: number
  checks: HealthCheck[]
  recent_errors: { at: string; path: string; status: number; detail: string }[]
}

export function fetchHealth() {
  return get<HealthDetail>('/api/health/detail')
}

// ── 관심종목 ───────────────────────────────────────────────────────
//
// 국내와 미국을 한 목록에 섞어 담는다. 그래서 항목마다 `market` 이 붙어 있고,
// 화면은 그것으로 현재가 표기(원/달러)와 상세 화면 종류를 가른다.
//
// **현재가는 이 응답에 없다.** 화면이 이미 `/api/prices` 를 5초마다 부르고 있어서,
// 같은 값을 두 경로로 받으면 둘이 어긋날 때 어느 쪽이 맞는지 알 수 없게 된다.
// 여기서 오는 것은 등락률 계산의 **기준가**뿐이다 — 그 출처가 시장마다 달라서
// (국내 KRX 확정 종가 / 미국 직전 일봉 종가) 기준일과 출처를 함께 들고 있다.

export type WatchItem = {
  symbol: string
  /** 'KR' | 'US' */
  market: string
  name: string
  group_name: string
  sort_order: number
  /** 등락률의 기준가. 못 구했으면 null — 등락률 자리만 비운다 */
  base_price: string | null
  base_date: string
  base_source: string
}

export type WatchList = {
  items: WatchItem[]
  max_items: number
}

export function fetchWatchlist() {
  return get<WatchList>('/api/watchlist')
}

/** 담기. 이미 담긴 종목이면 그대로 돌아온다(오류가 아니다). */
export function addToWatchlist(symbol: string) {
  return request<WatchItem>('/api/watchlist', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol }),
  })
}

export function removeFromWatchlist(symbol: string) {
  return request<{ removed: boolean }>(`/api/watchlist/${encodeURIComponent(symbol)}`, {
    method: 'DELETE',
  })
}

/** 한 칸 위/아래로. 이미 끝이면 아무 일도 일어나지 않는다. */
export function moveInWatchlist(symbol: string, direction: 'up' | 'down') {
  return request<{ status: string }>(`/api/watchlist/${encodeURIComponent(symbol)}/move`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ direction }),
  })
}

export type DisclosureItem = {
  receipt_no: string
  report_name: string
  filer_name: string
  received_date: string
  remark: string
  viewer_url: string
}

export type DisclosuresResponse = {
  stock_code: string
  corp_name: string
  corp_code: string
  period_days: number
  report_type: string | null
  report_type_label: string | null
  disclosures: DisclosureItem[]
}

/** 공시 목록. OpenDART 를 그때그때 부르므로 다른 조회보다 조금 느리다. */
export function fetchDisclosures(
  symbol: string,
  options: { days?: number; count?: number; reportType?: string | null } = {},
) {
  const params = new URLSearchParams({
    days: String(options.days ?? 365),
    count: String(options.count ?? 20),
  })
  if (options.reportType) params.set('report_type', options.reportType)
  return get<DisclosuresResponse>(`/api/stocks/${symbol}/disclosures?${params}`)
}

/** 현재가. 서버가 미리 받아 둔 값을 읽어 오므로 이 호출 자체는 외부 API 를 기다리지 않는다. */
export function fetchLivePrices(symbols: string[]) {
  return get<PricesResponse>(`/api/prices?symbols=${symbols.join(',')}`)
}


// ── 일정 캘린더 ────────────────────────────────────────────────────

/**
 * 캘린더에 찍히는 일정 하나.
 *
 * `editable` 이 거짓이면 자동으로 만들어진 일정이다(금통위·FOMC·만기). 고치거나 지울 수
 * 없고, `source` 에 어디서 온 값인지 적혀 있다.
 */
export type CalendarEvent = {
  event_date: string
  kind: string
  title: string
  editable: boolean
  id: number | null
  symbol: string | null
  memo: string | null
  source: string | null
  source_url: string | null
}

export type MonthEvents = {
  year: number
  month: number
  events: CalendarEvent[]
}

export function fetchMonthEvents(year: number, month: number) {
  return get<MonthEvents>(`/api/events/${year}/${month}`)
}

/**
 * 다가오는 일정 한 건.
 *
 * **`days_away` 를 서버가 세어 준다.** 브라우저에서 날짜를 빼면 시간대가 다를 때 하루
 * 어긋난다 — 서버는 한국 시간으로 센다.
 */
export type Upcoming = {
  event: CalendarEvent
  days_away: number
}

export function fetchUpcomingEvents(days = 60, limit = 4) {
  return get<Upcoming[]>(`/api/events/upcoming?days=${days}&limit=${limit}`)
}

export function createEvent(payload: {
  event_date: string
  kind: string
  title: string
  symbol?: string | null
  memo?: string | null
}) {
  return request<CalendarEvent>('/api/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function deleteEvent(id: number) {
  return request<{ removed: boolean }>(`/api/events/${id}`, { method: 'DELETE' })
}

// ── 기업 분석 (스크리너 · 동종업계 비교) ─────────────────────────
//
// 지표는 **미리 받아 둔 종목만** 안다. 그래서 응답에 `universe`(아는 종목 수)가 함께
// 오고, 화면은 그것을 반드시 밝힌다 — "조건에 맞는 종목 3개"와 "아는 300종목 중 3개"는
// 다른 말이다.

export type ScreenRow = {
  symbol: string
  name: string
  market: string
  price: number
  /** 미국 줄은 주가를 못 받으면 시총도 낼 수 없어 빈다. 국내는 항상 있다. */
  market_cap: number | null
  fiscal_year: number | null
  per: string | null
  pbr: string | null
  roe: string | null
  dividend_yield: string | null
  revenue_growth: string | null
}

export type ScreenResult = {
  trade_date: string
  universe: number
  matched: number
  rows: ScreenRow[]
  industry_code?: string | null
  /** 지주회사로 분류된 종목인가. 참이면 사업이 달라도 같은 업종으로 묶인다. */
  holding_company?: boolean
}

export type ScreenFilters = {
  per_max?: number | null
  pbr_max?: number | null
  roe_min?: number | null
  yield_min?: number | null
  growth_min?: number | null
  market?: string | null
  sort?: string
  desc?: boolean
  limit?: number
}

export function fetchScreen(filters: ScreenFilters) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value === null || value === undefined || value === '') continue
    params.set(key, String(value))
  }
  return get<ScreenResult>(`/api/screener?${params}`)
}

export function fetchPeers(symbol: string, limit = 10) {
  return get<ScreenResult>(`/api/screener/peers/${symbol}?limit=${limit}`)
}

/**
 * 미국 스크리너. 조건은 국내와 같고 응답 모양만 다르다.
 *
 * 국내 줄에 있는 것 중 여기 없는 것: 시장 구분(KOSPI/KOSDAQ)과 주가 기준일.
 * 미국에는 KRX 확정 종가 같은 물러설 자리가 없어 폴러가 받아 온 값을 그대로 쓴다.
 * 그래서 `priced` 로 몇 개가 주가까지 받아졌는지 함께 알린다.
 *
 * 숫자가 문자열인 것은 `UsPeerRow` 와 같은 이유다 — 서버가 Decimal 로 계산한 값을
 * 부동소수로 바꾸지 않고 그대로 넘긴다.
 */
export type UsScreenRow = {
  ticker: string
  name: string
  price: string | null
  market_cap: string | null
  fiscal_year: number | null
  per: string | null
  pbr: string | null
  roe: string | null
  dividend_yield: string | null
  revenue_growth: string | null
}

export type UsScreenResult = {
  universe: number
  matched: number
  /** 주가를 가진 회사 수. 이보다 적으면 일부 줄의 PER·시총이 비어 있다. */
  priced: number
  /** 주가를 받아 둔 시각(ISO). 국내의 '확정 종가 기준일'에 해당한다. */
  price_as_of: string | null
  rows: UsScreenRow[]
}

export function fetchUsScreen(filters: ScreenFilters) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    // market 은 미국에 없는 조건이다. 보내면 422 가 난다.
    if (key === 'market') continue
    if (value === null || value === undefined || value === '') continue
    params.set(key, String(value))
  }
  return get<UsScreenResult>(`/api/screener/us?${params}`)
}

/**
 * 미국 밸류에이션.
 *
 * 국내와 다른 점 하나: **발행주식수의 기준일이 재무 기간과 다르다.** SEC 가 주는
 * 수량은 가장 최근 제출 서류 표지의 값이라, 2025 회계연도 재무에 2026년 주식수가
 * 붙는다. 화면이 `shares_as_of` 를 반드시 밝힌다.
 */
export type UsValuation = {
  ticker: string
  name: string
  price: string
  shares_outstanding: number
  shares_as_of: string | null
  market_cap: string
  fiscal_year: number | null
  period_end: string | null
  eps: string | null
  bps: string | null
  dps: string | null
  per: string | null
  pbr: string | null
  dividend_yield: string | null
  per_note: string | null
  pbr_note: string | null
  dividend_note: string | null
}

export function fetchUsValuation(ticker: string) {
  return get<UsValuation>(`/api/us/${encodeURIComponent(ticker)}/valuation`)
}

/**
 * 미국 분기 재무(10-Q). 국내와 같은 모양이다 — 3개월치와 누적을 함께 담는다.
 *
 * **`period_end` 를 반드시 함께 본다.** 회계연도가 회사마다 달라서, 애플 FY2026 1분기는
 * 2025년 12월에 끝나고 마이크로소프트 FY2026 1분기는 2025년 9월에 끝난다.
 */
export type UsQuarterPoint = {
  fiscal_year: number
  quarter: number
  label: string
  period_end: string | null
  /** 4분기의 3개월 손익만 참 — 10-Q 가 없어 10-K 에서 빼서 구한다. */
  derived: boolean

  revenue: number | null
  gross_profit: number | null
  operating_income: number | null
  net_income: number | null

  revenue_cum: number | null
  gross_profit_cum: number | null
  operating_income_cum: number | null
  net_income_cum: number | null

  total_assets: number | null
  total_liabilities: number | null
  total_equity: number | null

  operating_margin: string | null
  net_margin: string | null
  operating_margin_cum: string | null
  net_margin_cum: string | null

  revenue_yoy: string | null
  operating_income_yoy: string | null
  revenue_cum_yoy: string | null
  operating_income_cum_yoy: string | null
}

export type UsQuarterly = {
  ticker: string
  cik: string
  name: string
  currency: string
  quarters: UsQuarterPoint[]
}

export function fetchUsQuarterly(ticker: string, quarters = 12) {
  return get<UsQuarterly>(
    `/api/us/${encodeURIComponent(ticker)}/financials/quarterly?quarters=${quarters}`,
  )
}

/**
 * 미국 동종업계 비교.
 *
 * **미리 받아 둔 종목 안에서만 나온다.** 미국은 회사 하나의 재무를 받는 데 3~4MB 짜리
 * 응답이 필요해서, 토스 거래대금 상위 100종목만 담아 둔다. `universe` 가 그 수다.
 *
 * 주가를 못 받은 종목은 지표가 비어 있고 이름만 나온다 — 목록에서 빼면 "그 회사가
 * 동종업계에 없다"로 잘못 읽힌다.
 */
export type UsPeerRow = {
  ticker: string
  name: string
  price: string | null
  market_cap: string | null
  fiscal_year: number | null
  per: string | null
  pbr: string | null
  roe: string | null
  revenue_growth: string | null
}

export type UsPeers = {
  ticker: string
  sic: string | null
  /** SEC 가 함께 주는 업종 이름. 국내(DART)는 코드만 있어 이게 없다. */
  sic_description: string | null
  universe: number
  rows: UsPeerRow[]
}

export function fetchUsPeers(ticker: string, limit = 10) {
  return get<UsPeers>(`/api/us/${encodeURIComponent(ticker)}/peers?limit=${limit}`)
}
