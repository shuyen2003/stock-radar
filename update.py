import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen

ROOT = Path("data")
ROOT.mkdir(exist_ok=True)

SOURCES = {
    "listed": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
    "otc": "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?response=json",
}

def download(url):
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 StockRadar/1.0",
        "Accept": "application/json"
    })
    with urlopen(request, timeout=45) as response:
        return json.load(response)

def main():
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    day = now.strftime("%Y-%m-%d")
    for market, url in SOURCES.items():
        print("Downloading:", market)
        data = download(url)
        if not data:
            raise RuntimeError("Empty response: " + market)
        output = ROOT / (market + "_raw.json")
        payload = {
            "fetched_at": now.isoformat(),
            "source": url,
            "data": data
        }
        output.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8"
        )
        archive = ROOT / ("archive_" + market)
        archive.mkdir(exist_ok=True)
        (archive / (day + ".json")).write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8"
        )
        print("Saved:", output)
    print("Collection completed; screening data not ready.")

if __name__ == "__main__":
    main()
