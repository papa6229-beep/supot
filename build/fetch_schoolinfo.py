# -*- coding: utf-8 -*-
"""학교알리미 공시정보에서 학교별 학년 학생수와 전입·전출 수를 받는다.

나이스 학교기본정보에는 학생 수가 없고, 학교알리미 파일 다운로드는 막혀 있다.
학교알리미 오픈API(apiType=10, 학년별·학급별 학생수)에 학년별 재학생과
전입(MVIN_SUM)·전출(MVT_SUM)이 함께 들어 있다.

키는 학교알리미에서 따로 받는다(공공데이터포털 키와 다르다).
    data/secrets/schoolinfo_key.txt   또는 환경변수 SCHOOLINFO_KEY
2026년 이후 발급 키는 시도(sidoCode 2자리)·시군구(sggCode 5자리)가 필수다.
일반구가 있는 시(성남·고양·부천 등)는 시 코드로는 비어 있어 구 코드로 부른다.
부천은 행정구가 폐지됐어도 옛 구 코드(41192 등)를 쓴다.

출처표시·변경금지(공공누리 3유형). 화면에 출처를 밝히고 숫자를 그대로 쓴다.

출력  data/raw/schoolinfo_2026.json
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / "data/secrets/schoolinfo_key.txt"
OUT = ROOT / "data/raw/schoolinfo_2026.json"
URL = "https://www.schoolinfo.go.kr/openApi.do"
YEAR = 2026
API_TYPE = 10                       # 학년별·학급별 학생수 (+ 전입·전출)
KINDS = {"02": "초등학교", "03": "중학교"}

sys.path.insert(0, str(ROOT / "build"))
from fetch_population import SIGUNGU  # noqa: E402  같은 56개 시군구


def read_key() -> str:
    key = os.environ.get("SCHOOLINFO_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        sys.exit(f"학교알리미 키가 없습니다: {KEY_FILE}")
    return key


def call(key: str, sgg: str, kind: str) -> list[dict] | None:
    q = urllib.parse.urlencode({"apiKey": key, "apiType": API_TYPE, "pbanYr": YEAR,
                                "schulKndCode": kind, "sidoCode": sgg[:2], "sggCode": sgg})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(f"{URL}?{q}", timeout=60) as r:
                d = json.loads(r.read().decode())
            return d.get("list") if d.get("resultCode") == "success" else None
        except Exception:
            time.sleep(1 + attempt * 2)
    return None


def main() -> None:
    key = read_key()
    rows, used = [], {}
    codes = [c[:5] for group in SIGUNGU.values() for c in group]
    for code in codes:
        # 시 코드로 비어 있으면 일반구 코드(끝자리 1~9)를 찾는다.
        tries = [code] if call(key, code, "03") else [code[:4] + str(d) for d in range(1, 10)]
        found = []
        for sgg in tries:
            got = 0
            for kind in KINDS:
                lst = call(key, sgg, kind) or []
                for x in lst:
                    x["_sgg"] = sgg
                rows.extend(lst)
                got += len(lst)
                time.sleep(0.1)
            if got:
                found.append(sgg)
        used[code] = found
        print(f"  {code} -> {', '.join(found) or '없음'}  누적 {len(rows):,}")

    OUT.write_text(json.dumps({"year": YEAR, "apiType": API_TYPE, "sgg": used, "list": rows},
                              ensure_ascii=False), encoding="utf-8")
    print(f"\n저장: {OUT.relative_to(ROOT)}  학교 {len(rows):,}곳")


if __name__ == "__main__":
    main()
