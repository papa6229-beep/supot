# -*- coding: utf-8 -*-
"""행정안전부 주민등록 인구통계에서 행정동별 1세 단위 인구를 받아 한 파일로 합친다.

jumin.mois.go.kr 은 시·군·구를 하나씩 지정해야 그 아래 행정동 목록을 준다.
그래서 서울 25 + 경기 31 = 56회를 돌려 이어붙인다.

출력: data/raw/pop_2026-08.csv  (UTF-8)
"""
import csv
import io
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/raw/pop_2026-08.csv"
ENDPOINT = "https://jumin.mois.go.kr/downloadCsvAge.do?searchYearMonth=month&xlsStats=1"
YEAR, MONTH = "2026", "08"
AGE_FROM, AGE_TO = 0, 19          # 초·중학생을 덮는 범위

SEOUL = "1100000000"
GYEONGGI = "4100000000"
SIGUNGU = {
    SEOUL: ["1111000000", "1114000000", "1117000000", "1120000000", "1121500000",
            "1123000000", "1126000000", "1129000000", "1130500000", "1132000000",
            "1135000000", "1138000000", "1141000000", "1144000000", "1147000000",
            "1150000000", "1153000000", "1154500000", "1156000000", "1159000000",
            "1162000000", "1165000000", "1168000000", "1171000000", "1174000000"],
    GYEONGGI: ["4111000000", "4113000000", "4115000000", "4117000000", "4119000000",
               "4121000000", "4122000000", "4125000000", "4127000000", "4128000000",
               "4129000000", "4131000000", "4136000000", "4137000000", "4139000000",
               "4141000000", "4143000000", "4145000000", "4146000000", "4148000000",
               "4150000000", "4155000000", "4157000000", "4159000000", "4161000000",
               "4163000000", "4165000000", "4167000000", "4180000000", "4182000000",
               "4183000000"],
}


def fetch(sido: str, sigungu: str) -> str:
    body = urllib.parse.urlencode({
        "sltOrgType": 2,             # 2 = 지정한 시·군·구의 행정동 목록
        "sltOrgLvl1": sido,
        "sltOrgLvl2": sigungu,
        "sum": "sum",
        "sltUndefType": "",
        "searchYearStart": YEAR, "searchMonthStart": MONTH,
        "searchYearEnd": YEAR, "searchMonthEnd": MONTH,
        "sltOrderType": 1, "sltOrderValue": "ASC",
        "sltArgTypes": 1,            # 1세 단위
        "sltArgTypeA": AGE_FROM, "sltArgTypeB": AGE_TO,
        "category": "month", "state": 1, "stateMobile": 1,
    }).encode()
    req = urllib.request.Request(
        ENDPOINT, data=body,
        headers={"Referer": "https://jumin.mois.go.kr/ageStatMonth.do",
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read().decode("cp949", errors="replace")


def main() -> None:
    header, rows = None, []
    total = sum(len(v) for v in SIGUNGU.values())
    done = 0

    for sido, codes in SIGUNGU.items():
        for code in codes:
            text = fetch(sido, code)
            done += 1
            table = list(csv.reader(io.StringIO(text)))
            if len(table) < 2:
                print(f"  ! 비어 있음: {code}", file=sys.stderr)
                continue
            if header is None:
                header = table[0]
            # 첫 행은 시·군·구 합계라 건너뛰고 행정동만 담는다.
            body = [r for r in table[1:] if r and "(" in r[0]]
            rows.extend(body[1:] if len(body) > 1 else body)
            print(f"  [{done}/{total}] {code}  행정동 {max(0, len(body)-1)}개")
            time.sleep(0.3)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"\n저장: {OUT.relative_to(ROOT)}  행정동 {len(rows):,}개")


if __name__ == "__main__":
    main()
