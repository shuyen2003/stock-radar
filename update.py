
import json
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path('data')
ROOT.mkdir(exist_ok=True)

SOURCES = {
    'listed': 'https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL',
    'otc': 'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?response=json',
}


def download(url):
    request = Request(url, headers={
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json',
    })
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def save(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False),
        encoding='utf-8'
    )


def number(value):
    try:
        return float(str(value).replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def trading_date(value):
    text = str(value).strip()

    if len(text) == 7 and text.isdigit():
        return (
            f'{int(text[:3]) + 1911:04d}-'
            f'{text[3:5]}-{text[5:7]}'
        )

    if len(text) == 8 and text.isdigit():
        return f'{text[:4]}-{text[4:6]}-{text[6:8]}'

    raise ValueError('Invalid trading date: ' + text)


def screen(history):
    dates = sorted(history)

    if len(dates) < 21:
        return []

    today = history[dates[-1]]
    results = []

    for code, item in today.items():
        series = [
            history[d].get(code)
            for d in dates[-21:]
        ]

        if any(
            not row or row['close'] <= 0 or row['volume'] <= 0
            for row in series
        ):
            continue

        previous = series[:-1]

        avg_volume = (
            sum(row['volume'] for row in previous) / 20
        )

        previous_high = max(
            row['close'] for row in previous
        )

        close = item['close']
        ratio = item['volume'] / avg_volume

        sma5 = (
            sum(row['close'] for row in series[-5:]) / 5
        )

        sma20 = (
            sum(row['close'] for row in previous) / 20
        )

        if not (
            ratio >= 1.8
            and close > previous_high
            and close > sma5 > sma20
        ):
            continue

        results.append({
            'code': code,
            'name': item['name'],
            'close': close,
            'volume_ratio': round(ratio, 2),
            'breakout_days': 20,
            'sma5': round(sma5, 2),
            'sma20': round(sma20, 2),
        })

    return sorted(
        results,
        key=lambda row: row['volume_ratio'],
        reverse=True
    )[:20]


def main():
    now = datetime.now(ZoneInfo('Asia/Taipei'))
    listed = None

    for market, url in SOURCES.items():
        raw = download(url)

        if not raw:
            raise RuntimeError('Empty data: ' + market)

        save(ROOT / f'{market}_raw.json', {
            'fetched_at': now.isoformat(),
            'source': url,
            'data': raw
        })

        if market == 'listed':
            if not isinstance(raw, list):
                raise ValueError('Invalid TWSE data type')
            listed = raw

    if not listed:
        raise ValueError('No TWSE stocks')

    date = trading_date(listed[0]['Date'])

    history_path = ROOT / 'listed_history.json'

    history = (
        json.loads(
            history_path.read_text(encoding='utf-8')
        )
        if history_path.exists()
        else {}
    )

    daily = {}

    for row in listed:
        code = str(row.get('Code', '')).strip()
        close = number(row.get('ClosingPrice'))
        volume = number(row.get('TradeVolume'))

        if not (code.isdigit() and len(code) == 4):
            continue

        if (
            close is None
            or volume is None
            or close <= 0
            or volume < 0
        ):
            continue

        daily[code] = {
            'name': str(row.get('Name', '')).strip(),
            'close': close,
            'volume': volume
        }

    if len(daily) < 500:
        raise ValueError('Too few valid TWSE stocks')

    history[date] = daily
    history = dict(sorted(history.items())[-90:])

    save(history_path, history)

    matches = screen(history)

    status = (
        '資料不足：至少需要21個交易日'
        if len(history) < 21
        else '上市技術面初篩完成；營收／法人／融資尚未接入'
    )

    save(ROOT / 'stocks.json', {
        'date': date,
        'status': status,
        'history_days': len(history),
        'stocks': matches,
    })

    print(
        'Date:', date,
        'History days:', len(history),
        'Matches:', len(matches)
    )

    print(
        'OTC raw data saved; OTC screening not yet enabled'
    )


if __name__ == '__main__':
    main()
