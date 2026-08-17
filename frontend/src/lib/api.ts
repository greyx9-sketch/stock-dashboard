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
}

export type SortKey = 'market_cap' | 'trade_value' | 'volume' | 'change_rate' | 'close'
export type MarketFilter = 'KOSPI' | 'KOSDAQ' | 'KONEX'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
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

export function fetchUsList(limit = 50) {
  return get<UsListItem[]>(`/api/us/list?limit=${limit}`)
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

export type UsAnalysis = {
  /** ok=분석 있음 / none=아직 안 함 / failed=실패 */
  status: 'ok' | 'none' | 'failed'
  ticker: string
  fiscal_year: number | null
  period_end: string | null
  filed_date: string | null
  source_url: string | null
  model: string | null
  generated_at: string | null
  sections: string[]
  truncated: string[]
  business_summary: string | null
  segments: string[]
  key_risks: UsRiskItem[]
  mdna_points: string[]
  moat_and_competition: string | null
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
  status: 'ok' | 'none' | 'failed'
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
  business_summary: string | null
  segments: string[]
  key_risks: KrRiskItem[]
  mdna_points: string[]
  moat_and_competition: string | null
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
