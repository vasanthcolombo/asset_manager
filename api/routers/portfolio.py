"""Portfolio positions endpoint."""

from fastapi import APIRouter, Depends

from api.deps import get_db, verify_token
from services.portfolio_engine import compute_portfolio

router = APIRouter(dependencies=[Depends(verify_token)])


@router.get("")
def get_portfolio(conn=Depends(get_db)):
    """Return all open positions with P&L metrics."""
    positions = compute_portfolio(conn)
    result = []
    for p in positions:
        result.append({
            "ticker": p.ticker,
            "name": p.name,
            "currency": p.currency,
            "country": p.country,
            "shares": p.shares,
            "live_price": p.live_price,
            "live_fx_rate": p.live_fx_rate,
            "cost_basis_per_share_native": p.cost_basis_per_share_native,
            "total_investment_sgd": p.total_investment_sgd,
            "cost_basis_sgd": p.cost_basis_sgd,
            "current_value_sgd": p.current_value_sgd,
            "unrealized_pnl_sgd": p.unrealized_pnl_sgd,
            "unrealized_pnl_pct": p.unrealized_pnl_pct,
            "realized_pnl_from_trades_sgd": p.realized_pnl_from_trades_sgd,
            "dividends_net_sgd": p.dividends_net_sgd,
        })
    return result


@router.get("/summary")
def portfolio_summary(conn=Depends(get_db)):
    """Return aggregate portfolio metrics."""
    positions = compute_portfolio(conn)
    total_value = sum(p.current_value_sgd for p in positions)
    total_cost = sum(p.cost_basis_sgd for p in positions)
    total_investment = sum(p.total_investment_sgd for p in positions)
    total_unrealized = sum(p.unrealized_pnl_sgd for p in positions)
    total_realized = sum(p.realized_pnl_from_trades_sgd for p in positions)
    total_dividends = sum(p.dividends_net_sgd for p in positions)
    return {
        "total_value_sgd": total_value,
        "total_cost_basis_sgd": total_cost,
        "total_investment_sgd": total_investment,
        "total_unrealized_pnl_sgd": total_unrealized,
        "total_realized_pnl_sgd": total_realized,
        "total_dividends_net_sgd": total_dividends,
        "total_pnl_sgd": total_unrealized + total_realized + total_dividends,
        "position_count": len(positions),
    }
