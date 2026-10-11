from pathlib import Path
import csv
base=Path(__file__).resolve().parents[1]/'reports'/'ym_sa'
def read(name):
    with (base/name).open(newline='',encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))
summary=read('portfolio_summary.csv')[0]
years=read('portfolio_yearly.csv')
trades=read('portfolio_trades.csv')
year_sum=sum(float(r['net_pnl']) for r in years)
trade_sum=sum(float(r['net_pnl']) for r in trades)
reported=float(summary['total_net_pnl'])
assert len(trades)==int(summary['N'])
assert abs(year_sum-reported)<0.01
assert abs(trade_sum-reported)<0.01
print(f"Consistent: {len(trades)} trades, ${reported:,.2f} simulated net P&L")
