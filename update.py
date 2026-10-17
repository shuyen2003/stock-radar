import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen

ROOT = Path("data")
ROOT.mkdir(exist_ok=True)

SOURCES = {
    "listed": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
    "otc": "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?response=json"
}

def download(url):
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    })
    with urlopen(req, timeout=60) as res:
        return json.load(res)

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False),
        encoding="utf-8"
    )

def number(value):
    try:
        return float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return None

def trading_date(raw):
    value = str(raw).strip()
    if len(value) == 7 and value.isdigit():
        return f"{int(value[:3])+1911:04d}-{value[3:5]}-{value[5:7]}"
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    raise ValueError("Unrecognized trading date: " + value)

def main():
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    listed = None
    for market, url in SOURCES.items():
        print("Downloading", market)
        raw = download(url)
        if not raw:
            raise RuntimeError("Empty response: " + market)
        save(ROOT / (market + "_raw.json"), {
            "fetched_at": now.isoformat(),
            "source": url,
            "data": raw
        })
        if market == "listed":
            if not isinstance(raw, list):
                raise ValueError("Unexpected listed format")
            listed = raw

    if not listed:
        raise ValueError("No listed data")

    date = trading_date(listed[0]["Date"])
    history_file = ROOT / "listed_history.json"
    history = {}
    if history_file.exists():
        history = json.loads(history_file.read_text(encoding="utf-8"))

    daily = {}
    for item in listed:
        code = str(item.get("Code", "")).strip()
        price = number(item.get("ClosingPrice"))
        volume = number(item.get("TradeVolume"))
        if not code or price is None or volume is None:
            continue
        if price <= 0 or volume < 0:
            continue
        daily[code] = {
            "name": str(item.get("Name", "")),
            "close": price,
            "volume": volume
        }

    if len(daily) < 500:
        raise ValueError("Too few valid listed stocks")

    history[date] = daily
    history = dict(sorted(history.items())[-90:])
    save(history_file, history)

    save(ROOT / "stocks.json", {
        "date": date,
        "status": "歷史行情累積中；完整選股資料尚未備妥",
        "history_days": len(history),
        "stocks": []
    })

    print("Listed trading date:", date)
    print("Listed stocks:", len(daily))
    print("History trading days:", len(history))
    print("OTC raw data saved; normalization pending")
    print("Finished without inventing screening signals")

if __name__ == "__main__":
    main()
