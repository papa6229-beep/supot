# -*- coding: utf-8 -*-
"""국토교통부 실거래가를 서울·경기 시군구별로 받아 한 파일로 합친다.

조회 단위가 「법정동코드 앞 5자리(시군구) + 계약년월」이고 응답에 법정동명이
들어 있어, 우리 법정동 단위와 그대로 맞물린다.

  상가(NrgTrade)   학원이 들어갈 수 있는 제2종근린생활 건물 시세, 용도지역
  아파트(AptTrade) 배후 학부모의 구매력

키는 저장소에 담지 않는다. data/secrets/data_go_kr_key.txt 또는 환경변수 DATA_GO_KR_KEY.

사용:
    python build/fetch_realestate.py nrg     # 상업업무용 매매
    python build/fetch_realestate.py apt     # 아파트 매매 (활용신청 필요)
"""
import csv
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / "data/secrets/data_go_kr_key.txt"
OUT_DIR = ROOT / "data/raw"

BASE_YM = (2026, 8)
MONTHS = 24                      # 거래가 드문드문해서 2년치를 모은다
PAUSE = 0.15

SERVICES = {
    "nrg": ("RTMSDataSvcNrgTrade", "상업업무용 매매"),
    "apt": ("RTMSDataSvcAptTrade", "아파트 매매"),
}

# fetch_population.py 와 같은 목록. LAWD_CD 는 앞 5자리만 쓴다.
SIGUNGU = [
    "1111000000", "1114000000", "1117000000", "1120000000", "1121500000",
    "1123000000", "1126000000", "1129000000", "1130500000", "1132000000",
    "1135000000", "1138000000", "1141000000", "1144000000", "1147000000",
    "1150000000", "1153000000", "1154500000", "1156000000", "1159000000",
    "1162000000", "1165000000", "1168000000", "1171000000", "1174000000",
    "4111000000", "4113000000", "4115000000", "4117000000", "4119000000",
    "4121000000", "4122000000", "4125000000", "4127000000", "4128000000",
    "4129000000", "4131000000", "4136000000", "4137000000", "4139000000",
    "4141000000", "4143000000", "4145000000", "4146000000", "4148000000",
    "4150000000", "4155000000", "4157000000", "4159000000", "4161000000",
    "4163000000", "4165000000", "4167000000", "4180000000", "4182000000",
    "4183000000",
]


def read_key() -> str:
    key = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        sys.exit(f"공공데이터포털 키가 없습니다: {KEY_FILE}")
    return key


def months_back(n: int) -> list[str]:
    y, m = BASE_YM
    out = []
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def fetch(service: str, key: str, lawd: str, ym: str) -> list[dict]:
    url = (f"https://apis.data.go.kr/1613000/{service}/get{service}?"
           + urllib.parse.urlencode({"serviceKey": key, "LAWD_CD": lawd,
                                     "DEAL_YMD": ym, "pageNo": 1, "numOfRows": 1000}))
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                root = ET.fromstring(r.read().decode())
            return [{c.tag: (c.text or "").strip() for c in item}
                    for item in root.findall(".//item")]
        except (urllib.error.HTTPError, urllib.error.URLError, ET.ParseError):
            time.sleep(1 + attempt * 2)
    print(f"  ! 실패 {lawd} {ym}", file=sys.stderr)
    return []


def main(kind: str) -> None:
    service, label = SERVICES[kind]
    key = read_key()
    yms = months_back(MONTHS)
    rows, fields = [], []
    total = len(SIGUNGU) * len(yms)
    done = 0

    print(f"{label} — 시군구 {len(SIGUNGU)} × {len(yms)}개월 = {total}회")
    for lawd10 in SIGUNGU:
        lawd = lawd10[:5]
        got = 0
        for ym in yms:
            for item in fetch(service, key, lawd, ym):
                for k in item:
                    if k not in fields:
                        fields.append(k)
                rows.append(item)
                got += 1
            done += 1
            time.sleep(PAUSE)
        print(f"  [{done:>5}/{total}] {lawd}  누적 {len(rows):,}건 (이 지역 {got:,})")

    out = OUT_DIR / f"realestate_{kind}_{BASE_YM[0]}-{BASE_YM[1]:02d}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"\n저장: {out.relative_to(ROOT)}  {len(rows):,}건")


if __name__ == "__main__":
    kind = sys.argv[1] if len(sys.argv) > 1 else "nrg"
    if kind not in SERVICES:
        sys.exit(f"사용: python build/fetch_realestate.py [{'|'.join(SERVICES)}]")
    main(kind)
