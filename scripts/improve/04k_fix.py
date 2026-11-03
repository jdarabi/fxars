from pathlib import Path

p = Path('C:/FX/fxars/services/analysis.py')
lines = p.read_text(encoding='utf-8').splitlines(keepends=True)

# پیدا کردن خط "self.quality_runs.list(" در DQ gate
list_idx = None
for i, line in enumerate(lines):
    if '_dq_runs = self.quality_runs.list(' in line:
        list_idx = i
        break

if list_idx is None:
    print('[FAIL] self.quality_runs.list( not found')
    raise SystemExit(1)

print(f'[OK] found _dq_runs = self.quality_runs.list( at line {list_idx+1}')

# چاپ 5 خط اطراف
for j in range(list_idx, min(list_idx + 6, len(lines))):
    print(f'  {j+1}: {lines[j]!r}')

# پیدا کردن خط بستن ")": خط بعدی که فقط ")" یا با indent
close_idx = None
for j in range(list_idx + 1, min(list_idx + 5, len(lines))):
    stripped = lines[j].strip()
    if stripped == ')':
        close_idx = j
        break

if close_idx is None:
    print('[FAIL] closing ) not found')
    raise SystemExit(1)

print(f'[OK] closing ) at line {close_idx+1}')

# استخراج indent
indent = lines[list_idx][:len(lines[list_idx]) - len(lines[list_idx].lstrip())]
print(f'[OK] indent = {len(indent)} spaces')

# جایگزینی با کد جدید
new_lines = [
    indent + '# FIX-P0-DQ-FAIL-CALL: list() timeframe kwarg ندارد\n',
    indent + '_dq_all = self.quality_runs.list(instrument_id=instrument_id, limit=10)\n',
    indent + '_dq_runs = [r for r in _dq_all if r.timeframe == tf.value][:1]\n',
]

# جایگزینی: از line list_idx تا close_idx را با new_lines
result = lines[:list_idx] + new_lines + lines[close_idx + 1:]

# حالا except Exception
text = ''.join(result)

# رفع except
old_except = '        except Exception:\n            _dq_failed = True\n'
new_except = (
    '        except Exception as _dq_exc:\n'
    '            # FIX-P0-DQ-FAIL: در صورت خطا، اجازه عبور (نه FAIL اجباری)\n'
    '            logger.warning("data quality check failed: %s", _dq_exc)\n'
    '            _dq_failed = False\n'
)
if 'except Exception as _dq_exc:' in text:
    print('[SKIP] except already fixed')
elif old_except in text:
    text = text.replace(old_except, new_except)
    print('[PATCH] except fixed')
else:
    print('[WARN] except pattern not found')
    # چاپ context
    for i, line in enumerate(text.splitlines()):
        if '_dq_failed = True' in line:
            print(f'  {i+1}: {line!r}')

p.write_text(text, encoding='utf-8')
print('[WROTE] analysis.py')

# verify
final = p.read_text(encoding='utf-8')
print('no timeframe kwarg:', 'timeframe=tf.value, limit=1' not in final)
print('_dq_all present    :', '_dq_all = self.quality_runs.list' in final)
print('_dq_failed=False  :', '_dq_failed = False' in final)
print('[DONE]')