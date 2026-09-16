# -*- coding: utf-8 -*-
"""소규모상가 임대료·공실률을 구·시 단위로 옮긴다.

부동산원은 지역을 '명동'·'목동'·'상계역' 같은 **상권** 이름으로 준다.
우리 화면은 구·시 단위라 짝을 지어야 하는데, 손으로 맞추면 틀리기 쉬워서
상권 이름을 카카오로 좌표 변환한 뒤 그 좌표가 어느 구에 있는지 되묻는다.

한 구에 상권이 여럿이면(강남구: 강남대로·논현역·압구정·청담…) 중간값을 쓴다.
상권이 하나도 없는 구는 값이 없다. 추정으로 메우지 않는다.

입력  data/raw/rent_small_retail.csv
출력  web/data/rent.json
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/raw/rent_small_retail.csv"
OUT = ROOT / "web/data/rent.json"
CACHE = ROOT / "data/geo/rent_areas.csv"
KEY_FILE = ROOT / "data/secrets/kakao_rest_key.txt"

KEYWORD_API = "https://dapi.kakao.com/v2/local/search/keyword.json"
REGION_API = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json"


def read_key() -> str:
    key = os.environ.get("KAKAO_REST_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        sys.exit(f"카카오 REST 키가 없습니다: {KEY_FILE}")
    return key


def get(url: str, params: dict, key: str) -> dict | None:
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                 headers={"Authorization": "KakaoAK " + key})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def locate(area: str, sido: str, key: str) -> str | None:
    """'서울>기타>목동' -> '양천구'. 상권 이름을 찾아 그 좌표의 구·시를 돌려준다."""
    leaf = area.split(">")[-1]
    # '신촌/이대'처럼 둘을 붙여놓은 이름은 앞쪽만 쓴다.
    leaf = re.split(r"[/·]", leaf)[0].strip()
    hit = get(KEYWORD_API, {"query": f"{sido} {leaf}", "size": 1}, key)
    docs = (hit or {}).get("documents") or []
    if not docs:
        return None
    d = docs[0]
    reg = get(REGION_API, {"x": d["x"], "y": d["y"]}, key)
    for doc in (reg or {}).get("documents", []):
        if doc.get("region_type") == "B" and doc.get("region_2depth_name"):
            # 경기는 '성남시 분당구'로 와서 시까지만 남긴다.
            return doc["region_2depth_name"].split()[0]
    return None


def area_to_gusi(areas: list[tuple[str, str]], key: str) -> dict[str, str]:
    done: dict[str, str] = {}
    if CACHE.exists():
        df = pd.read_csv(CACHE, dtype=str).fillna("")
        done = {r.상권: r.구시 for r in df.itertuples() if r.구시}

    todo = [(a, s) for a, s in areas if a not in done]
    for i, (area, sido) in enumerate(todo, 1):
        gusi = locate(area, sido, key)
        if gusi:
            done[area] = gusi
        else:
            print(f"  ? 못 찾음: {area}", file=sys.stderr)
        time.sleep(0.05)

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"상권": a, "구시": g} for a, g in sorted(done.items())]).to_csv(
        CACHE, index=False, encoding="utf-8")
    return done


def main() -> None:
    if not SRC.exists():
        sys.exit(f"원본이 없습니다: {SRC}  (build/fetch_rent.py 먼저)")

    df = pd.read_csv(SRC)
    df = df[df["시점"] == df["시점"].max()].copy()
    # 잎 노드만. '서울>강남' 같은 권역 합계는 뺀다.
    depth = df["상권"].str.count(">")
    df = df[((df["시도"] == "서울") & (depth == 2)) | ((df["시도"] == "경기") & (depth == 1))]

    mapping = area_to_gusi(list(zip(df["상권"], df["시도"])), read_key())
    df["구시"] = df["상권"].map(mapping)
    df = df.dropna(subset=["구시"])

    out = {}
    for (sido, gusi), g in df.groupby(["시도", "구시"]):
        out[f"{sido}/{gusi}"] = {
            "rent": round(float(g["임대료"].median()), 1),      # 천원/㎡ · 월
            "vacancy": round(float(g["공실률"].median()), 1),   # %
            "areas": sorted(a.split(">")[-1] for a in g["상권"]),
        }

    payload = {
        "quarter": df["시점명"].iloc[0],
        "source": "한국부동산원 상업용부동산 임대동향조사 · 소규모상가",
        "note": ("표본 조사 추정치다. 상가 임대차는 신고 의무가 없어 건별 실거래가 없다. "
                 "지역끼리 견주는 용도로만 읽고, 실제 조건은 발품으로 확인해야 한다."),
        "unit": {"rent": "천원/㎡ (월 환산임대료)", "vacancy": "%"},
        "gusi": out,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"저장: {OUT.relative_to(ROOT)}  구·시 {len(out)}개 ({df['시점명'].iloc[0]})")


if __name__ == "__main__":
    main()
