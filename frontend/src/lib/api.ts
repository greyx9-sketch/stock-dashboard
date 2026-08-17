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
