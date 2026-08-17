"""관심종목 엔드포인트.

**이 프로젝트에서 화면이 서버 상태를 바꾸는 유일한 곳이다**(분석 실행은 결과를 캐시할 뿐이다).
읽기 전용 대시보드라는 원칙과 어긋나 보이지만, 관심종목은 사용자 자신의 목록이고
기획서 DB 설계에도 `watchlist` 테이블이 있다. 매매·계좌와는 무관하다.

브라우저 저장소를 쓰지 않으므로(절대 규칙 6) 목록은 서버 DB 에 있다. 그래서 어느 기기에서
열어도 같은 목록이 보인다.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from app.services import watchlist as service

router = APIRouter(prefix="/api/watchlist", tags=["관심종목"])

SYMBOL_PATH = Path(description="국내 6자리 종목코드 또는 미국 티커", min_length=1, max_length=20)


class ItemOut(BaseModel):
    symbol: str
    market: str = Field(description="KR / US")
    name: str
    group_name: str
    sort_order: int
    base_price: Decimal | None = Field(
        description="등락률의 기준가. 국내는 KRX 확정 종가, 미국은 직전 일봉 종가"
    )
    base_date: str = Field(description="기준가의 거래일. 화면에 함께 보여준다")
    base_source: str = Field(description="기준가의 출처. 시장마다 다르다")


class ListOut(BaseModel):
    items: list[ItemOut]
    max_items: int = Field(description="담을 수 있는 상한")


class AddIn(BaseModel):
    symbol: str = Field(description="국내 6자리 종목코드 또는 미국 티커", min_length=1, max_length=20)


class MoveIn(BaseModel):
    direction: str = Field(description="up 또는 down")


def _out(item: service.Item) -> ItemOut:
    return ItemOut(**vars(item))


@router.get("", summary="관심종목 목록")
async def get_watchlist() -> ListOut:
    """담아 둔 종목과 각자의 기준가를 돌려준다.

    현재가는 여기서 주지 않는다. 화면이 이미 `/api/prices` 를 5초마다 부르고 있으므로
    같은 값을 두 경로로 내려 두면 둘이 어긋날 때 어느 쪽이 맞는지 알 수 없게 된다.
    """
    items = await service.list_items()
    return ListOut(items=[_out(i) for i in items], max_items=service.MAX_ITEMS)


@router.post("", summary="관심종목 담기", status_code=200)
async def add_to_watchlist(body: AddIn) -> ItemOut:
    """목록에 담는다. 이미 있으면 그대로 돌려준다 — 두 번 눌러도 오류가 아니다."""
    try:
        return _out(await service.add(body.symbol))
    except service.WatchlistError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{symbol}", summary="관심종목 빼기")
def remove_from_watchlist(symbol: str = SYMBOL_PATH) -> dict[str, bool]:
    """목록에서 뺀다. 없던 종목이어도 404 로 만들지 않는다 — 결과가 같기 때문이다."""
    return {"removed": service.remove(symbol)}


@router.post("/{symbol}/move", summary="순서 옮기기")
def move_in_watchlist(body: MoveIn, symbol: str = SYMBOL_PATH) -> dict[str, str]:
    """한 칸 위나 아래로 옮긴다. 이미 끝이면 아무 일도 하지 않는다."""
    try:
        service.move(symbol, body.direction)
    except service.WatchlistError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok"}
