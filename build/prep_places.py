# -*- coding: utf-8 -*-
"""지도에 찍을 지점(학원·학교)을 동별로 묶어 JSON으로 낸다.

목록에서 동을 누르면 그 동 파일 하나만 받아서 지도에 뿌린다.
전부 한 파일에 담으면 1MB가 넘어 첫 화면이 느려지므로 동 단위로 쪼갠다.

입력  data/raw/aca_2026-08.csv, school_2026-08.csv, dongmap.csv
      data/geo/coords.csv            (geocode.py 가 만든 주소->좌표)
출력  web/data/places/<시도>_<구시>_<동>.json
      web/data/places/index.json     (어느 동에 파일이 있는지)
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
COORDS = ROOT / "data/geo/coords.csv"
OUT_DIR = ROOT / "web/data/places"

sys.path.insert(0, str(ROOT / "build"))
from prep import (BASE_YM, UNKNOWN_DONG, known_dongs, load_academies,  # noqa: E402
                  load_dongmap, load_schools)

SAFE = re.compile(r"[^0-9A-Za-z가-힣]+")


def slug(*parts: str) -> str:
    """파일 이름으로 쓸 수 있게 다듬는다. 동 이름에 '·'나 공백이 섞여 있다."""
    return "_".join(SAFE.sub("", p) for p in parts)


def load_coords() -> dict[str, tuple[float, float]]:
    df = pd.read_csv(COORDS, dtype=str).fillna("")
    df = df[df["정확도"] != "실패"]
    return {r.주소: (float(r.lat), float(r.lng)) for r in df.itertuples()}


def main() -> None:
    if not COORDS.exists():
        sys.exit(f"좌표가 없습니다. 먼저 build/geocode.py 를 돌리세요: {COORDS}")

    coords = load_coords()
    known = known_dongs(load_dongmap())
    aca = load_academies(known)
    sch = load_schools(known)

    eng = aca[aca["영어"]].copy()
    eng["종류"] = "학원"
    eng["세부"] = eng.apply(
        lambda r: "교습소" if r["학원교습소명"] == "교습소"
        else ("영어+타 과목" if r["복합"] else "영어 전문"), axis=1)
    eng["표시명"] = eng["학원명"]
    eng["연도"] = eng["개설연도"]

    sch = sch.copy()
    sch["종류"] = "학교"
    sch["세부"] = sch["학교종류명"]
    sch["표시명"] = sch["학교명"]
    sch["연도"] = pd.to_numeric(sch["설립일자"].str.slice(0, 4), errors="coerce")

    cols = ["시도", "구시", "동", "종류", "세부", "표시명", "연도", "도로명주소"]
    places = pd.concat([eng[cols], sch[cols]], ignore_index=True)
    places = places[places["동"] != UNKNOWN_DONG]

    xy = places["도로명주소"].str.strip().map(coords)
    places = places[xy.notna()].copy()
    places["lat"] = [round(v[0], 6) for v in xy[xy.notna()]]
    places["lng"] = [round(v[1], 6) for v in xy[xy.notna()]]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.json"):
        old.unlink()

    index = {}
    for (sido, gusi, dong), g in places.groupby(["시도", "구시", "동"], sort=False):
        name = slug(sido, gusi, dong)
        items = [{
            "n": r.표시명,
            "t": "s" if r.종류 == "학교" else "a",   # school / academy
            "k": r.세부,
            "y": int(r.연도) if pd.notna(r.연도) else None,
            "lat": r.lat, "lng": r.lng,
        } for r in g.itertuples()]
        (OUT_DIR / f"{name}.json").write_text(
            json.dumps({"sido": sido, "gusi": gusi, "dong": dong, "items": items},
                       ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
        index[f"{sido}/{gusi}/{dong}"] = {
            "f": name,
            "a": sum(1 for i in items if i["t"] == "a"),
            "s": sum(1 for i in items if i["t"] == "s"),
        }

    (OUT_DIR / "index.json").write_text(
        json.dumps({"base_ym": BASE_YM, "dongs": index}, ensure_ascii=False,
                   separators=(",", ":")), encoding="utf-8")

    total = sum(len(json.loads((OUT_DIR / f"{v['f']}.json").read_text(encoding='utf-8'))["items"])
                for v in index.values())
    size = sum(f.stat().st_size for f in OUT_DIR.glob("*.json")) / 1024
    print(f"저장: {OUT_DIR.relative_to(ROOT)}  파일 {len(index):,}개  합계 {size:,.0f} KB")
    print(f"  지점 {total:,}개 (학원 {sum(v['a'] for v in index.values()):,} / "
          f"학교 {sum(v['s'] for v in index.values()):,})")
    print(f"  좌표 못 붙인 지점 {len(places) and '':>0}", end="")
    print(f"— 전체 대상 대비 {total:,}개 수록")


if __name__ == "__main__":
    main()
