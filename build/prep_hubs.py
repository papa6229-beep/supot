# -*- coding: utf-8 -*-
"""큰 학원가까지의 직선거리를 동·구마다 잰다.

학원가 목록과 '어디서 학생을 끌어들이는가'는 학부모 조사 문서(2026.09)를 따른다.
여기에 우리 데이터로 영어학원이 100곳 넘게 모인 동(다산·동탄 반송·부천 중동·상동)을 더했다.
그 흐름은 위키·블로그에서 반복되는 통설이고 정량 통계가 아니다. 화면에도 그렇게 적는다.
거리는 우리 좌표로 잰 사실이다.
  - 학원가 중심: 그 동들에 있는 영어학원 좌표의 가운데(중앙값)
  - 동 위치: 그 동 안 학원·학교 좌표의 가운데
  - 구·시 위치: 그 구에 속한 동 위치들의 가운데

입력  web/data/places/*.json, web/data/regions.json
출력  web/data/hubs.json
"""
import json
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACES = ROOT / "web/data/places"
OUT = ROOT / "web/data/hubs.json"
RADIUS_KM = 1.5

# id, 이름, 학원가를 이루는 동, 통설 설명, 통설상 학생이 오는 곳(구·시 단위, 동 단위)
HUBS = [
    {"id": "daechi", "name": "대치동 학원가", "dongs": ["서울/강남구/대치동"],
     "lore": "전국의 상위권 수요를 빨아들이는 최종 도착지. 잠실·서초 등 인근 부촌 상위권까지 흡수한다.",
     "from_gu": ["서울/강남구", "서울/서초구"], "from_dong": ["서울/송파구/잠실동"]},
    {"id": "mokdong", "name": "목동 학원가", "dongs": ["서울/양천구/목동", "서울/양천구/신정동"],
     "lore": "초·중등 사교육과 특목·자사고 입시가 강하다. 서울 서남권 수요를 흡수하고, 최상위권 일부는 대치로 간다.",
     "from_gu": ["서울/양천구", "서울/강서구", "서울/구로구", "서울/영등포구"], "from_dong": []},
    {"id": "junggye", "name": "중계동 은행사거리", "dongs": ["서울/노원구/중계동"],
     "lore": "강북 대표 학군. 노원·도봉·강북·중랑과 경기 의정부·남양주·구리·양주 수요가 반복해서 거론된다.",
     "from_gu": ["서울/노원구", "서울/도봉구", "서울/강북구", "서울/중랑구",
                 "경기/의정부시", "경기/남양주시", "경기/구리시", "경기/양주시"], "from_dong": []},
    {"id": "pyeongchon", "name": "평촌 학원가", "dongs": ["경기/안양시/평촌동", "경기/안양시/호계동"],
     "lore": "서울을 빼면 수도권 최대급 학원가. 안양·과천·의왕·군포에서, 가끔 안산·시흥에서 온다.",
     "from_gu": ["경기/안양시", "경기/과천시", "경기/의왕시", "경기/군포시", "경기/안산시", "경기/시흥시"],
     "from_dong": []},
    {"id": "bundang", "name": "분당 정자·수내·서현", "dongs": ["경기/성남시/정자동", "경기/성남시/수내동", "경기/성남시/서현동"],
     "lore": "대치 대형학원 분원이 모인 곳. 구성남·수원·용인·광주 등 경기 동남부 상위권이 온다.",
     "from_gu": ["경기/성남시", "경기/수원시", "경기/용인시", "경기/광주시"], "from_dong": []},
    {"id": "ilsan", "name": "일산 후곡·백마", "dongs": ["경기/고양시/일산동", "경기/고양시/마두동"],
     "lore": "서북부 사교육 중심. 후곡은 대형학원 위주이고 운정(파주)·화정·행신·능곡·원당·삼송·구파발에서 온다.",
     "from_gu": ["경기/고양시", "경기/파주시"], "from_dong": ["서울/은평구/진관동"]},
    # 문서 목록에는 없지만 우리 데이터로 영어학원이 100곳 넘게 모인 동. 통설이 없으니 설명을 달지 않는다.
    {"id": "dasan", "name": "다산 학원가", "dongs": ["경기/남양주시/다산동"], "kind": "data",
     "lore": "", "from_gu": [], "from_dong": []},
    {"id": "dongtan", "name": "동탄 반송동 학원가", "dongs": ["경기/화성시/반송동"], "kind": "data",
     "lore": "", "from_gu": [], "from_dong": []},
    {"id": "bucheon", "name": "부천 중동·상동 학원가", "dongs": ["경기/부천시/중동", "경기/부천시/상동"], "kind": "data",
     "lore": "", "from_gu": [], "from_dong": []},
]


# 큰 학원가는 아니지만 자체 학원가가 생기는 중이라는 통설이 있는 곳 (구·시 단위)
LOCAL_LORE = {
    "경기/하남시": "미사강변도시는 강동구 강일동과 맞닿아 있고, 근린상가(스타힐스·센트럴자이)를 중심으로 "
                   "자체 학원가가 생기는 중이다. 강동·잠실 원정도 가깝다.",
    "경기/김포시": "한강신도시(장기·운양·구래·마산)는 구래동 중심상업지구가 가장 큰 학원가다.",
    "경기/남양주시": "다산·별내는 자체 학원가를 만드는 중이고, 상위권은 중계동 원정을 병행한다는 통설이 있다. "
                     "다만 원정 비율을 보여주는 자료는 확인되지 않았다.",
}


def km(a, b):
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(h))


def center(points):
    return (st.median(p[0] for p in points), st.median(p[1] for p in points))


def main() -> None:
    index = json.loads((PLACES / "index.json").read_text(encoding="utf-8"))["dongs"]
    regions = json.loads((ROOT / "web/data/regions.json").read_text(encoding="utf-8"))
    eng = {f'{r["sido"]}/{r["parent"]}/{r["name"]}': r["eng_total"] for r in regions["dong"]}

    dong_pos, hub_pts = {}, defaultdict(list)
    hub_of = {k: h["id"] for h in HUBS for k in h["dongs"]}
    every = []                                   # 반경 세기용: 모든 동의 학원·학교
    for key, meta in index.items():
        items = json.loads((PLACES / f'{meta["f"]}.json').read_text(encoding="utf-8"))["items"]
        every += [i for i in items if i["t"] in ("a", "s")]
        pts = [(i["lat"], i["lng"]) for i in items if i["t"] in ("a", "s")]
        if pts:
            dong_pos[key] = center(pts)
        if key in hub_of:
            hub_pts[hub_of[key]] += [(i["lat"], i["lng"]) for i in items if i["t"] == "a"]

    hubs = []
    for h in HUBS:
        c = center(hub_pts[h["id"]])
        # 동 경계와 상관없이 중심에서 1.5km 안. 학원가는 동 경계를 넘어 퍼져 있다.
        near = [i for i in every if km(c, (i["lat"], i["lng"])) <= RADIUS_KM]
        ring = {"eng": sum(i["t"] == "a" for i in near),
                "inst": sum(i["t"] == "a" and i["k"] == "교습소" for i in near),
                "sch": sum(i["t"] == "s" for i in near),
                "stu": sum(i.get("tg", 0) for i in near if i["t"] == "s")}
        hubs.append({"id": h["id"], "name": h["name"], "lat": round(c[0], 5), "lng": round(c[1], 5), "ring": ring,
                     "dongs": h["dongs"], "eng": sum(eng.get(k, 0) for k in h["dongs"]),
                     "lore": h["lore"], "from_gu": h["from_gu"], "from_dong": h["from_dong"],
                     "kind": h.get("kind", "doc")})

    def nearest(pos):
        ds = sorted((km(pos, (h["lat"], h["lng"])), h["id"]) for h in hubs)
        return {"hub": ds[0][1], "km": round(ds[0][0], 1), "hub2": ds[1][1], "km2": round(ds[1][0], 1)}

    dongs = {k: nearest(p) for k, p in dong_pos.items()}
    by_gu = defaultdict(list)
    for k, p in dong_pos.items():
        sido, gusi, _ = k.split("/")
        by_gu[f"{sido}/{gusi}"].append(p)
    gus = {k: nearest(center(v)) for k, v in by_gu.items()}

    OUT.write_text(json.dumps({
        "radius_km": RADIUS_KM,
        "source": "학원가 목록·유입 흐름: 학부모 조사 문서(2026.09) — 위키·블로그 통설, 정량 통계 아님. 거리: 우리 좌표로 잰 직선거리.",
        "hubs": hubs, "dongs": dongs, "gus": gus, "local_lore": LOCAL_LORE,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"저장: {OUT.relative_to(ROOT)}  ({OUT.stat().st_size / 1024:.0f} KB)  동 {len(dongs)} · 구시 {len(gus)}")
    for h in hubs:
        print(f"  {h['name']:<14} 영어학원 {h['eng']:>4}곳 · 반경 {RADIUS_KM}km {h['ring']['eng']:>4}곳  ({h['lat']}, {h['lng']})")
    for k in ["경기/남양주시/다산동", "경기/의정부시/신곡동", "경기/하남시/망월동", "경기/김포시/장기동", "서울/은평구/진관동", "경기/화성시/반송동"]:
        print("  ", k, dongs.get(k))


if __name__ == "__main__":
    main()
