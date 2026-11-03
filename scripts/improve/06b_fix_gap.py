from pathlib import Path
import sys

p = Path('C:/FX/fxars/research/backtest.py')
text = p.read_text(encoding='utf-8')

if 'FIX-06-GAP-STOP' in text:
    print('[SKIP] gap stop already patched')
else:
    old = '''        pip = self._pip
        if position.direction is Direction.LONG:
            if candle.low <= position.stop:
                exit_price = position.stop - self.config.slippage_pips * pip
                return self._close(position, exit_price, "STOP_LOSS", candle, equity)
            if not position.tp1_hit and candle.high >= position.tp1:
                self._partial(position, position.tp1)
            elif position.tp1_hit and candle.high >= position.tp2:
                return self._close(position, position.tp2, "TARGET_2", candle, equity)
        else:
            if candle.high >= position.stop:
                exit_price = position.stop + self.config.slippage_pips * pip
                return self._close(position, exit_price, "STOP_LOSS", candle, equity)
            if not position.tp1_hit and candle.low <= position.tp1:
                self._partial(position, position.tp1)
            elif position.tp1_hit and candle.low <= position.tp2:
                return self._close(position, position.tp2, "TARGET_2", candle, equity)'''

    new = '''        pip = self._pip
        # FIX-06-GAP-STOP: Gap-aware Stop Loss.
        if position.direction is Direction.LONG:
            stop_fill = None
            if candle.open < position.stop:
                stop_fill = candle.open - self.config.slippage_pips * pip
            elif candle.low <= position.stop:
                stop_fill = position.stop - self.config.slippage_pips * pip
            if stop_fill is not None:
                return self._close(position, stop_fill, "STOP_LOSS", candle, equity)
            if not position.tp1_hit and candle.high >= position.tp1:
                self._partial(position, position.tp1)
            elif position.tp1_hit and candle.high >= position.tp2:
                return self._close(position, position.tp2, "TARGET_2", candle, equity)
        else:
            stop_fill = None
            if candle.open > position.stop:
                stop_fill = candle.open + self.config.slippage_pips * pip
            elif candle.high >= position.stop:
                stop_fill = position.stop + self.config.slippage_pips * pip
            if stop_fill is not None:
                return self._close(position, stop_fill, "STOP_LOSS", candle, equity)
            if not position.tp1_hit and candle.low <= position.tp1:
                self._partial(position, position.tp1)
            elif position.tp1_hit and candle.low <= position.tp2:
                return self._close(position, position.tp2, "TARGET_2", candle, equity)'''

    if old not in text:
        print('[FAIL] _process_bar anchor not found')
        sys.exit(1)
    text = text.replace(old, new)
    p.write_text(text, encoding='utf-8')
    print('[PATCH 06b] gap-aware stop')
print('[DONE 06b]')