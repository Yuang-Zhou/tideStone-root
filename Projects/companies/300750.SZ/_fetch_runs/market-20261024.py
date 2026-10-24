"""Single-company onboarding retrieval; delegates to the existing market engine."""
import hashlib
import json
import io
import subprocess
import socket
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'Projects/_system/scripts'))
import market_data_fetcher as market
import akshare as ak

assert market.OUTPUT_DIR.resolve() == ROOT / 'Projects/_system/market_data'
assert market.AK_TICKERS.get('300750.SZ') == '300750'
socket.setdefaulttimeout(20)
started = datetime.now(ZoneInfo('Asia/Shanghai'))
stamp = started.strftime('%Y%m%d-%H%M%S')
report_path = Path(__file__).with_name(f'market-{stamp}.json')
events = []

def trace(source, func):
    def wrapped(*args, **kwargs):
        event = {'source': source, 'started_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
        events.append(event)
        print(f'Attempt: {source}', flush=True)
        try:
            expressions = {
                'baostock': "market._fetch_baostock('300750', date(2018,6,11), date(2026,10,23))",
                'tencent_via_akshare': "ak.stock_zh_a_hist_tx(symbol='sz300750', start_date='20180611', end_date='20261023', adjust='qfq', timeout=20)",
                'eastmoney_via_akshare': "ak.stock_zh_a_hist(symbol='300750', period='daily', start_date='20180611', end_date='20261023', adjust='qfq', timeout=20)",
            }
            code = "import sys, socket\nfrom datetime import date\nsocket.setdefaulttimeout(20)\n"
            code += f"sys.path.insert(0, {str(ROOT / 'Projects/_system/scripts')!r})\n"
            code += "import market_data_fetcher as market\nimport akshare as ak\n"
            code += f"df = {expressions[source]}\n"
            code += "if df is not None:\n for c in ('date','日期'):\n  if c in df.columns: df[c]=df[c].astype(str)\n"
            code += "print('TIDESTONE_DF=' + ('null' if df is None else df.to_json(orient='split')))\n"
            completed = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                                       timeout=90 if source == 'tencent_via_akshare' else 45)
            if completed.returncode:
                raise RuntimeError((completed.stderr or completed.stdout)[-2500:])
            payload = next((line[len('TIDESTONE_DF='):] for line in completed.stdout.splitlines() if line.startswith('TIDESTONE_DF=')), None)
            if payload is None:
                raise RuntimeError('Source did not return a dataframe marker: '+completed.stdout[-1000:])
            import pandas as pd
            frame = None if payload == 'null' else pd.read_json(io.StringIO(payload), orient='split', convert_dates=False)
            event.update(status='empty' if frame is None or frame.empty else 'returned', rows=0 if frame is None else len(frame))
            if frame is not None and not frame.empty:
                event['source_columns'] = list(frame.columns)
            return frame
        except Exception as exc:
            event.update(status='error', error=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            event['finished_at'] = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
            report_path.write_text(json.dumps({'ticker':'300750.SZ','status':'running','attempts':events}, ensure_ascii=False, indent=2)+'\n')
    return wrapped

market._fetch_baostock = trace('baostock', market._fetch_baostock)
ak.stock_zh_a_hist_tx = trace('tencent_via_akshare', ak.stock_zh_a_hist_tx)
ak.stock_zh_a_hist = trace('eastmoney_via_akshare', ak.stock_zh_a_hist)
market.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
if '--tencent-only' in sys.argv:
    fetcher = lambda repair_log=None: market._normalize_a_share_columns(ak.stock_zh_a_hist_tx(
        symbol='sz300750', start_date='20180611', end_date='20261023', adjust='qfq', timeout=20))
else:
    fetcher = lambda repair_log=None: market.fetch_akshare_stock('300750', date(2018, 6, 11), date(2026, 10, 23))
ok, message, entry = market.run_one('CN', '300750.SZ', '300750',
    fetcher, market.OUTPUT_DIR)
report = {
    'ticker': '300750.SZ', 'started_at': started.isoformat(),
    'finished_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
    'requested_start': '2018-06-11', 'requested_end': '2026-10-23',
    'adjustment': '前复权（baostock adjustflag=2；腾讯/东财 adjust=qfq）',
    'ok': ok, 'message': message, 'attempts': events, 'entry': entry,
    'engine': 'Projects/_system/scripts/market_data_fetcher.py run_one + normalization; ' + ('Tencent-only retry after baostock transport timeouts' if '--tencent-only' in sys.argv else 'fetch_akshare_stock'),
}
csv_path = market.OUTPUT_DIR / '300750.SZ.csv'
if ok and csv_path.exists():
    import pandas as pd
    frame = pd.read_csv(csv_path, dtype={'date': str})
    report.update(actual_first_date=frame['date'].min(), actual_last_date=frame['date'].max(),
                  actual_rows=len(frame), covers_2026_10_23=frame['date'].max() >= '2026-10-23',
                  csv_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                  duplicate_dates=int(frame['date'].duplicated().sum()),
                  incomplete_ohlc_rows=int(frame[['open','high','low','close']].isna().any(axis=1).sum()))
    report['successful_source'] = next((e['source'] for e in reversed(events) if e['status']=='returned'), None)
    market.rebuild_manifest_from_csvs()
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
log_dir = market.OUTPUT_DIR / 'fetch_log'
log_dir.mkdir(exist_ok=True)
(log_dir / f'market-300750.SZ-{stamp}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
sys.exit(0 if ok else 2)
