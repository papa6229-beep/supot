# -*- coding: utf-8 -*-
"""한국부동산원 상업용부동산 임대동향조사에서 소규모상가 임대료·공실률을 받는다.

소규모상가 = 2층 이하·연면적 330㎡ 이하. 교습소나 작은 학원이 들어가는 규모다.

주의: 이 자료는 실거래가 아니라 **표본 조사 추정치**다. 상가 임대차는 신고 의무가
없어 국가가 건별 계약을 모으지 못한다. "양천구가 평택시보다 비싸다" 정도의
상대 비교로만 읽어야 하고, 화면에도 추정치임을 밝힌다.

지역 단위도 우리 법정동이 아니라 **상권**(서울 64 · 경기 35)이다.
그래서 구·시 지표에만 붙이고 지도에는 올리지 않는다.

키는 R-ONE(reb.or.kr) 것으로, 공공데이터포털 키와 다르다.
    data/secrets/reb_key.txt

출력: data/raw/rent_small_retail.csv
"""
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / "data/secrets/reb_key.txt"
OUT = ROOT / "data/raw/rent_small_retail.csv"
API = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"

# 2024년 3분기부터의 최신 조사판
TABLES = {
    "임대료": "T248223134698125",     # ㎡당 월 환산임대료 (천원/㎡)
    "공실률": "T241833134686576",     # %
    "전환율": "T246253134905233",     # 보증금->월세 전환율 %
}


def read_key() -> str:
    key = os.environ.get("REB_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        sys.exit(f"R-ONE 키가 없습니다: {KEY_FILE}")
    return key


def fetch_table(key: str, statbl_id: str) -> list[dict]:
    out: list[dict] = []
    for page in range(1, 60):
        url = API + "?" + urllib.parse.urlencode(
            {"KEY": key, "Type": "json", "pIndex": page, "pSize": 1000,
             "STATBL_ID": statbl_id, "DTACYCLE_CD": "QY"})
        with urllib.request.urlopen(url, timeout=90) as r:
            body = json.loads(r.read().decode())
        if "SttsApiTblData" not in body:
            break
        rows = body["SttsApiTblData"][1]["row"]
        out.extend(rows)
        if len(rows) < 1000:
            break
        time.sleep(0.2)
    return out


def main() -> None:
    key = read_key()
    merged: dict[tuple, dict] = {}

    for label, statbl_id in TABLES.items():
        rows = fetch_table(key, statbl_id)
        for r in rows:
            area = (r.get("CLS_FULLNM") or "").strip()
            if not area.startswith(("서울", "경기")):
                continue
            k = (area, r["WRTTIME_IDTFR_ID"])
            rec = merged.setdefault(k, {
                "상권": area, "시도": area.split(">")[0],
                "시점": r["WRTTIME_IDTFR_ID"], "시점명": r.get("WRTTIME_DESC", ""),
            })
            rec[label] = r.get("DTA_VAL")
        print(f"  {label:5} {len(rows):,}행")

    rows = sorted(merged.values(), key=lambda x: (x["시점"], x["상권"]))
    fields = ["시도", "상권", "시점", "시점명", *TABLES]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    latest = max(r["시점"] for r in rows)
    cur = [r for r in rows if r["시점"] == latest]
    print(f"\n저장: {OUT.relative_to(ROOT)}  {len(rows):,}행")
    print(f"  최신 {cur[0]['시점명']} · 상권 {len(cur)}개 "
          f"(서울 {sum(1 for r in cur if r['시도'] == '서울')} / "
          f"경기 {sum(1 for r in cur if r['시도'] == '경기')})")


if __name__ == "__main__":
    main()
