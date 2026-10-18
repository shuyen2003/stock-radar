"""台股飆股雷達 V2：上市歷史行情回補、每日更新、技術面初篩。

第一次執行：從證交所每日歷史行情補足 21 個不同交易日。
之後執行：保留已累積資料，僅補足缺少的日期。
僅保存證交所實際回傳、通過驗證的資料，不補造假日行情。
"""
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent / 'data'
ROOT.mkdir(parents=True, exist_ok=True)
TODAY_SNAPSHOT = 'https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL'
TWSE_HISTORY = 'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX'
OTC_SNAPSHOT = 'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?response=json'
MIN_STOCKS = 500
HISTORY_REQUIRED = 21
MAX_CALENDAR_DAYS = 55  # 含週末、國定假日和可能的臨時休市


def get_json(url, retries=3):
    last_error = None
    for attempt in range(retries):
        try:
            request = Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; stock-radar/2.0)',
                'Accept': 'application/json',
                'Referer': 'https://www.twse.com.tw/',
            })
            with urlopen(request, timeout=35) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f'抓取失敗：{url}: {last_error}')


def save(path, payload):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    temp.replace(path)


def number(value):
    try:
        text = str(value).replace(',', '').strip()
        if text in ('', '--', '---', 'X', '除權', '除息'):
            return None
        value = float(text)
        return value if value == value and abs(value) != float('inf') else None
    except (ValueError, TypeError):
        return None


def trading_date(value):
    text = str(value).strip()
    if len(text) == 7 and text.isdigit():
        result = date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:7]))
    elif len(text) == 8 and text.isdigit():
        result = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    else:
        raise ValueError(f'無法解析交易日：{value!r}')
    return result.isoformat()


def validate_daily(daily):
    return isinstance(daily, dict) and len(daily) >= MIN_STOCKS


def snapshot_to_daily(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError('證交所當日行情格式不正確')
    trade_dates = {trading_date(row['Date']) for row in rows if isinstance(row, dict) and row.get('Date')}
    if len(trade_dates) != 1:
        raise ValueError(f'當日資料的日期不一致：{trade_dates}')
    daily = {}
    for row in rows:
        code = str(row.get('Code', '')).strip()
        close = number(row.get('ClosingPrice'))
        volume = number(row.get('TradeVolume'))
        if re.fullmatch(r'\d{4}', code) and close is not None and close > 0 and volume is not None and volume >= 0:
            daily[code] = {'name': str(row.get('Name', '')).strip(), 'close': close, 'volume': volume}
    if not validate_daily(daily):
        raise ValueError(f'當日上市行情股票數量異常：{len(daily)}')
    return next(iter(trade_dates)), daily


def historical_to_daily(day):
    """抓取證交所指定日期的上市全市場行情；休市日回傳 None。"""
    qs = urlencode({'response': 'json', 'date': day.strftime('%Y%m%d'), 'type': 'ALLBUT0999'})
    data = get_json(f'{TWSE_HISTORY}?{qs}', retries=2)
    if not isinstance(data, dict):
        raise ValueError('歷史行情不是 JSON 物件')
    stat = str(data.get('stat', ''))
    if stat and stat != 'OK':
        # 休市或無行情；不得將空資料記成交易日。
        if any(s in stat.lower() for s in ('沒有', '查無', '無資料', '休市', 'no data')):
            return None
        raise ValueError(f'{day} 證交所歷史查詢異常：{stat}')
    tables = list(data.get('tables') or [])
    # API 依日期不同可能用 tables 或 tables8/tables9 等命名。
    for key, value in data.items():
        if key.startswith('tables') and key != 'tables' and isinstance(value, list):
            tables.extend(value)
    if data.get('fields') and data.get('data'):
        tables.append(data)
    candidates = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        fields = [str(v).strip() for v in (table.get('fields') or [])]
        if not all(any(required in field for field in fields) for required in ('證券代號', '成交股數', '收盤價')):
            continue
        candidates.append((fields, table.get('data') or []))
    if not candidates:
        # 有成交資料、卻無法辨識股票表時，應報錯而非偽裝休市。
        if stat == 'OK':
            raise ValueError(f'{day} 歷史欄位格式不符合預期')
        return None
    daily = {}
    for fields, rows in candidates:
        def pos(keyword):
            return next(i for i, field in enumerate(fields) if keyword in field)
        code_i, name_i = pos('證券代號'), next((i for i, f in enumerate(fields) if '證券名稱' in f), None)
        close_i, volume_i = pos('收盤價'), pos('成交股數')
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) <= max(code_i, close_i, volume_i):
                continue
            code = re.sub(r'[^0-9]', '', str(row[code_i]).replace('=', ''))
            close, volume = number(row[close_i]), number(row[volume_i])
            if re.fullmatch(r'\d{4}', code) and close is not None and close > 0 and volume is not None and volume >= 0:
                daily[code] = {'name': str(row[name_i]).strip() if name_i is not None else code,
                               'close': close, 'volume': volume}
    if not validate_daily(daily):
        raise ValueError(f'{day} 歷史行情筆數異常：{len(daily)}')
    return daily


def screen(history):
    dates = sorted(history)
    if len(dates) < HISTORY_REQUIRED:
        return []
    today = history[dates[-1]]
    results = []
    for code, item in today.items():
        series = [history[d].get(code) for d in dates[-21:]]
        if any(not row or row['close'] <= 0 or row['volume'] <= 0 for row in series):
            continue
        previous = series[:-1]
        avg_volume = sum(row['volume'] for row in previous) / 20
        if avg_volume <= 0:
            continue
        previous_high = max(row['close'] for row in previous)
        close, ratio = item['close'], item['volume'] / avg_volume
        sma5 = sum(row['close'] for row in series[-5:]) / 5
        sma20 = sum(row['close'] for row in previous) / 20
        if ratio >= 1.8 and close > previous_high and close > sma5 > sma20:
            results.append({'code': code, 'name': item['name'], 'close': close,
                            'volume_ratio': round(ratio, 2), 'breakout_days': 20,
                            'sma5': round(sma5, 2), 'sma20': round(sma20, 2),
                            'breakout20': True, 'trend': True})
    return sorted(results, key=lambda row: row['volume_ratio'], reverse=True)[:20]


def main():
    now = datetime.now(ZoneInfo('Asia/Taipei'))
    history_path = ROOT / 'listed_history.json'
    history = json.loads(history_path.read_text(encoding='utf-8')) if history_path.exists() else {}
    history = {k: v for k, v in history.items() if validate_daily(v) and k <= now.date().isoformat()}

    # 當日最新收盤快照。即使連線有問題，也保留原來已累積的歷史資料。
    try:
        listed = get_json(TODAY_SNAPSHOT)
        latest_date, latest_daily = snapshot_to_daily(listed)
        history[latest_date] = latest_daily
        save(ROOT / 'listed_raw.json', {'fetched_at': now.isoformat(), 'source': TODAY_SNAPSHOT, 'data': listed})
    except Exception as exc:
        print(f'上市最新快照取得失敗：{exc}')
        if not history:
            raise
        latest_date = max(history)

    # 既有上櫃原始快照繼續保留，上櫃技術面選股尚未開放。
    try:
        otc = get_json(OTC_SNAPSHOT, retries=2)
        if otc:
            save(ROOT / 'otc_raw.json', {'fetched_at': now.isoformat(), 'source': OTC_SNAPSHOT, 'data': otc})
    except Exception as exc:
        print(f'上櫃快照暫時無法取得：{exc}')

    # 回補歷史交易日；跳過週末與休市日，不複製行情或假造日期。
    cursor = date.fromisoformat(latest_date) - timedelta(days=1)
    attempts = 0
    while len([d for d in history if d <= latest_date]) < HISTORY_REQUIRED and attempts < MAX_CALENDAR_DAYS:
        if cursor.weekday() < 5:
            key = cursor.isoformat()
            if key not in history:
                try:
                    daily = historical_to_daily(cursor)
                    if daily:
                        history[key] = daily
                        print(f'歷史回補 {key}: {len(daily)} 檔')
                        # 保存中間結果，中斷後下次可以從已回補資料繼續。
                        save(history_path, dict(sorted(history.items())[-90:]))
                    else:
                        print(f'{key}: 休市或沒有行情')
                except Exception as exc:
                    print(f'{key}: 回補失敗（下次可重試）：{exc}')
                time.sleep(0.7)
        cursor -= timedelta(days=1)
        attempts += 1

    history = dict(sorted(history.items())[-90:])
    save(history_path, history)
    history_days = len([d for d in history if d <= latest_date])
    matches = screen({d: history[d] for d in sorted(history) if d <= latest_date})
    status = ('資料不足：至少需要21個交易日' if history_days < HISTORY_REQUIRED
              else '上市技術面初篩完成；營收／法人／融資尚未接入')
    # 搜尋功能和強勢股候選名單分開：歷史尚未滿21天也能查全部上市股票。
    latest_items = history.get(latest_date, {})
    universe = []
    for code, item in latest_items.items():
        record = {'code': code, 'name': item['name'], 'close': item['close'],
                  'volume': item['volume']}
        dates_for_code = [d for d in sorted(history) if d <= latest_date and
                          code in history[d] and history[d][code]['close'] > 0]
        if len(dates_for_code) >= 21:
            last21 = [history[d][code] for d in dates_for_code[-21:]]
            avg_vol = sum(r['volume'] for r in last21[:-1]) / 20
            if avg_vol > 0:
                record['volume_ratio'] = round(last21[-1]['volume'] / avg_vol, 2)
            record['sma5'] = round(sum(r['close'] for r in last21[-5:]) / 5, 2)
            record['sma20'] = round(sum(r['close'] for r in last21[:-1]) / 20, 2)
            record['breakout20'] = last21[-1]['close'] > max(r['close'] for r in last21[:-1])
            record['trend'] = (record['close'] > record['sma5'] > record['sma20'])
        universe.append(record)
    save(ROOT / 'stocks.json', {'date': latest_date, 'status': status,
                               'history_days': history_days, 'stocks': matches,
                               'universe': universe, 'market': '上市',
                               'updated_at': now.isoformat()})
    print(f'Date: {latest_date} History days: {history_days} Matches: {len(matches)}')
    if history_days < HISTORY_REQUIRED:
        print('注意：歷史行情尚未補足21個交易日。請檢查上方失敗訊息，勿將0檔誤認為篩選結果。')
    print('OTC raw data saved when available; OTC screening not yet enabled')


if __name__ == '__main__':
    main()
