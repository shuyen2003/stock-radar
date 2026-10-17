import json
from pathlib import Path

DATA = Path("data")

def load(filename):
    path = DATA / filename
    if not path.exists():
        print(filename, "檔案不存在")
        return None
    return json.loads(path.read_text(encoding="utf-8"))

def main():
    print("台股飆股雷達 V2：資料檢查")
    for name in ["listed_raw.json", "otc_raw.json"]:
        content = load(name)
        if content is None:
            continue
        raw = content.get("data") if isinstance(content, dict) else content
        print(name, "資料類型:", type(raw).__name__)
        if isinstance(raw, list):
            print("資料筆數:", len(raw))
        elif isinstance(raw, dict):
            print("資料欄位:", list(raw.keys()))

    history = load("listed_history.json")
    if isinstance(history, dict):
        print("上市歷史交易日:", len(history))
        print("最近日期:", sorted(history)[-5:])
    
    stocks = load("stocks.json")
    if isinstance(stocks, dict):
        print("網站股票筆數:", len(stocks.get("stocks", [])))

    print("檢查完成：未修改任何股票資料")

if __name__ == "__main__":
    main()
