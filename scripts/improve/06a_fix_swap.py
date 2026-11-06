import sys
from pathlib import Path

p = Path('C:/FX/fxars/research/backtest.py')
text = p.read_text(encoding='utf-8')

if 'FIX-06-SWAP' in text:
    print('[SKIP] swap already patched')
else:
    old_init = '''        self._pip = instrument.pip_size
        self._contract = instrument.contract_size
        self._quant = Decimal(1).scaleb(-instrument.digits)'''
    new_init = '''        self._pip = instrument.pip_size
        self._contract = instrument.contract_size
        self._quant = Decimal(1).scaleb(-instrument.digits)
        # FIX-06-SWAP: مدت هر کندل به دقیقه، برای محاسبه دقیق Swap
        from fxars.domain.enums import Timeframe as _TF
        self._tf_minutes = _TF.parse(timeframe).minutes'''
    if old_init not in text:
        print('[FAIL] __init__ anchor not found')
        sys.exit(1)
    text = text.replace(old_init, new_init)

    old_close = '''        commission = self.config.commission_per_lot * position.volume
        nights = Decimal(position.bars_held) / Decimal("24")
        swap = self.config.swap_per_lot_per_night * position.volume * nights'''
    new_close = '''        commission = self.config.commission_per_lot * position.volume
        # FIX-06-SWAP: nights = bars * (timeframe_minutes / 1440)
        minutes_held = Decimal(position.bars_held) * Decimal(self._tf_minutes)
        nights = minutes_held / Decimal("1440")
        swap = self.config.swap_per_lot_per_night * position.volume * nights'''
    if old_close not in text:
        print('[FAIL] _close anchor not found')
        sys.exit(1)
    text = text.replace(old_close, new_close)

    p.write_text(text, encoding='utf-8')
    print('[PATCH 06a] swap timeframe-aware')
print('[DONE 06a]')
