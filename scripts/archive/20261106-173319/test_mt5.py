# C:\FX\test_mt5.py
import MetaTrader5 as mt5
from datetime import datetime, timezone

if not mt5.initialize():
    print('initialize FAIL:', mt5.last_error())
    raise SystemExit(1)

# 1) اطلاعات حساب
info = mt5.account_info()
if info is None:
    print('account_info FAIL:', mt5.last_error())
else:
    print('=== Account ===')
    print('login   :', info.login)
    print('server  :', info.server)
    print('currency:', info.currency)
    print('balance :', info.balance)
    print('equity  :', info.equity)
    print('leverage:', info.leverage)

# 2) نمادها
symbols = mt5.symbols_get()
print()
print('=== Symbols ===')
print('Total:', len(symbols) if symbols else 0)
for s in (symbols or [])[:10]:
    print(' ', s.name)

# 3) کندل EURUSD/H1
print()
print('=== EURUSD/H1 last 5 candles ===')
rates = mt5.copy_rates_from_pos('EURUSD', mt5.TIMEFRAME_H1, 0, 5)
if rates is None:
    print('copy_rates FAIL:', mt5.last_error())
else:
    for r in rates:
        ts = datetime.fromtimestamp(int(r['time']), tz=timezone.utc)
        print(
            f"  {ts.isoformat()} "
            f"O={r['open']:.5f} H={r['high']:.5f} "
            f"L={r['low']:.5f} C={r['close']:.5f} V={r['tick_volume']}"
        )

# 4) نمادهای هدف
print()
print('=== Target symbols ===')
for symbol in ['EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY']:
    si = mt5.symbol_info(symbol)
    if si is None:
        print(f'  {symbol}: NOT FOUND')
    else:
        print(
            f'  {symbol}: digits={si.digits} '
            f'point={si.point} contract={si.trade_contract_size} '
            f'spread={si.spread}'
        )

mt5.shutdown()
print()
print('Done.')