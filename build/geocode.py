# -*- coding: utf-8 -*-
"""학원·학교 주소를 카카오 로컬 API로 좌표로 바꾼다.

원본(나이스)에는 위경도가 없고 도로명주소만 있어서 지도에 찍으려면 변환이 필요하다.
같은 주소가 여러 번 나오므로(한 건물에 학원 여럿) 주소 단위로 묶어서 한 번만 부른다.

키는 저장소에 담지 않는다. 환경변수나 로컬 파일에서 읽는다.
    setx KAKAO_REST_KEY "..."        (또는)
    data/secrets/kakao_rest_key.txt

사용:
    python build/geocode.py            # 아직 안 된 주소만 이어서 변환
    python build/geocode.py --retry    # 실패로 기록된 것도 다시 시도

출력: data/geo/coords.csv   (주소, lat, lng, 정확도)
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/geo/coords.csv"
KEY_FILE = ROOT / "data/secrets/kakao_rest_key.txt"

ADDRESS_API = "https://dapi.kakao.com/v2/local/search/address.json"
KEYWORD_API = "https://dapi.kakao.com/v2/local/search/keyword.json"
PAUSE = 0.04                 # 초당 25건 정도. 카카오 권장 범위 안쪽.
SAVE_EVERY = 200             # 중간에 끊겨도 이어서 할 수 있게 자주 저장한다.


def read_key() -> str:
    key = os.environ.get("KAKAO_REST_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        sys.exit(f"카카오 REST 키가 없습니다. 환경변수 KAKAO_REST_KEY 또는 {KEY_FILE}")
    return key


def call(url: str, params: dict, key: str) -> dict | None:
    req = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params),
        headers={"Authorization": "KakaoAK " + key})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:            # 호출 한도. 잠깐 쉬었다 다시.
                time.sleep(2 + attempt * 3)
                continue
            return None
        except Exception:
            time.sleep(1 + attempt)
    return None


def geocode(address: str, key: str) -> tuple[float, float, str] | None:
    """도로명주소로 먼저 찾고, 없으면 건물명까지 붙여 키워드로 한 번 더 찾는다."""
    got = call(ADDRESS_API, {"query": address, "size": 1}, key)
    docs = (got or {}).get("documents") or []
    if docs:
        d = docs[0]
        return float(d["y"]), float(d["x"]), "주소"

    got = call(KEYWORD_API, {"query": address, "size": 1}, key)
    docs = (got or {}).get("documents") or []
    if docs:
        d = docs[0]
        return float(d["y"]), float(d["x"]), "키워드"
    return None


def load_done() -> dict[str, list[str]]:
    if not OUT.exists():
        return {}
    with OUT.open(encoding="utf-8") as f:
        return {r["주소"]: [r["lat"], r["lng"], r["정확도"]] for r in csv.DictReader(f)}


def save(done: dict[str, list[str]]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["주소", "lat", "lng", "정확도"])
        for addr, (lat, lng, how) in done.items():
            w.writerow([addr, lat, lng, how])


def wanted_addresses() -> list[str]:
    """지도에 찍을 대상의 주소 모음. 같은 주소는 한 번만."""
    sys.path.insert(0, str(ROOT / "build"))
    from prep import load_academies, load_dongmap, load_schools, known_dongs

    known = known_dongs(load_dongmap())
    aca = load_academies(known)
    sch = load_schools(known)
    addrs = list(aca.loc[aca["영어"], "도로명주소"]) + list(sch["도로명주소"])
    return sorted({a.strip() for a in addrs if a and a.strip()})


def main(retry: bool) -> None:
    key = read_key()
    done = load_done()
    if retry:
        done = {a: v for a, v in done.items() if v[2] != "실패"}

    targets = [a for a in wanted_addresses() if a not in done]
    print(f"대상 주소 {len(done) + len(targets):,}개 중 새로 변환할 것 {len(targets):,}개")

    for i, addr in enumerate(targets, 1):
        hit = geocode(addr, key)
        done[addr] = [hit[0], hit[1], hit[2]] if hit else ["", "", "실패"]
        if i % SAVE_EVERY == 0:
            save(done)
            ok = sum(1 for v in done.values() if v[2] != "실패")
            print(f"  {i:,}/{len(targets):,}  성공 누적 {ok:,}")
        time.sleep(PAUSE)

    save(done)
    ok = sum(1 for v in done.values() if v[2] != "실패")
    print(f"\n저장: {OUT.relative_to(ROOT)}")
    print(f"  주소 {len(done):,}개 / 좌표 확보 {ok:,}개 ({ok/len(done)*100:.1f}%)")


if __name__ == "__main__":
    main("--retry" in sys.argv)
