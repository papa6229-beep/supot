# -*- coding: utf-8 -*-
"""영어학원 개원시장 동별 분석 문서(docx)를 동별 자료로 옮긴다.

문서는 우리 동 목록(서울+인접 경기 432행)을 받아 동마다 '시장 유형'을 붙인
조사 보고서다. 동별 실측이 아니라 대부분 유형 추정(E2)이라는 점을 자료에도
그대로 남긴다. 화면은 이 등급을 먼저 보여줘야 한다.

원본은 개인 표현이 섞여 있어 저장소에 올리지 않는다(.gitignore).
    data/raw/market_analysis_2026-09.docx

출력  web/data/market.json
"""
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/raw/market_analysis_2026-09.docx"
OUT = ROOT / "web/data/market.json"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# 문서의 '우선 검토군'은 동 이름을 줄여 적었다. 법정동이 아닌 생활권 이름은 여기서 푼다.
# 미사강변도시는 하남시 망월동·풍산동 일대다.
AREA_ALIAS = {"미사": ["망월동", "풍산동"], "일산동(후곡)": ["일산동"]}

# 경기도 2027 고입 기본계획상 비평준화인 시(문서 별첨 1-3). 우리 대상 안에서만.
NON_LEVELED = ["김포시", "하남시", "남양주시", "구리시"]

# 근거 등급을 화면에 옮길 때 쓰는 말
GRADES = {
    "E1": {"label": "직접 확인", "text": "2026년에 이 동·생활권의 학원 자료를 직접 확인했습니다."},
    "E2": {"label": "유형 추정", "text": "이 동을 직접 조사한 것이 아니라, 같은 유형의 대표 지역과 제도를 바탕으로 추정했습니다."},
    "E3": {"label": "현장 확인 먼저", "text": "온라인 자료가 부족한 곳입니다. 계약 판단 전에 현장을 먼저 봐야 합니다."},
}


def cell_text(tc) -> str:
    """한 칸의 문단들을 줄바꿈으로 잇는다."""
    return "\n".join("".join(t.text or "" for t in p.iter(W + "t")) for p in tc.iter(W + "p")).strip()


def tables(path: Path) -> list[list[list[str]]]:
    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    out = []
    for tbl in root.iter(W + "tbl"):
        out.append([[cell_text(tc) for tc in tr.findall(W + "tc")] for tr in tbl.iter(W + "tr")])
    return out


def split_labeled(text: str, labels: list[str]) -> dict[str, str]:
    """'앞문장\\n부모: …\\n영어동기: …' 를 칸별로 가른다. 줄바꿈이 없어도 라벨로 가른다."""
    flat = text.replace("\n", " ")
    pat = "(" + "|".join(re.escape(l) for l in labels) + ")"
    parts = re.split(pat, flat)
    out = {"_": parts[0].strip()}
    for i in range(1, len(parts) - 1, 2):
        out[parts[i].rstrip(":").strip()] = parts[i + 1].strip()
    return out


def main() -> None:
    if not SRC.exists():
        sys.exit(f"원본이 없습니다: {SRC}")
    tbls = tables(SRC)

    # --- 유형 설명 ---------------------------------------------------------
    type_tbl = next(t for t in tbls if t[0][:2] == ["코드", "시장유형"])
    # 적합 형태·핵심 위험 칸은 동별 표의 형태·주의와 같은 문장이라 거기서 채운다.
    types = {r[0]: {"name": r[1], "motive": r[2]} for r in type_tbl[1:]}

    # --- 동별 판정 ---------------------------------------------------------
    dongs, dup_rows, fixed_rows, total = {}, 0, 0, 0
    template = {}   # 유형별 기본 판단문. 이와 다르면 그 동만을 위해 쓴 문장이다.
    rows = []
    for t in tbls:
        if t[0][:4] != ["No.", "원본구분", "실제지역", "동"]:
            continue
        for r in t[1:]:
            total += 1
            no, orig, real, dong, typ, judge, prod, ev = r
            rows.append((no, orig, real, dong, typ, judge, prod, ev))
    for *_, typ, judge, _, _ in rows:
        code = typ[:2]
        first = split_labeled(judge, ["부모:", "영어동기:"])["_"]
        template.setdefault(code, {}).setdefault(first, 0)
        template[code][first] += 1

    for no, orig, real, dong, typ, judge, prod, ev in rows:
        if "중복행" in ev:
            dup_rows += 1
            continue
        if "구역정정" in ev or "행정동 명칭" in ev:
            fixed_rows += 1
        sido, gusi = real.split()[:2]
        code = typ[:2]
        j = split_labeled(judge, ["부모:", "영어동기:"])
        p = split_labeled(prod, ["메시지:", "주의:"])
        common = max(template[code], key=template[code].get)
        grade = ev[:2]
        # 부모·동기·형태·메시지·주의는 같은 유형이면 문장이 똑같다. 유형 쪽에 한 번만 둔다.
        types[code].update({
            "summary": common,
            "parent": j.get("부모", ""),
            "form": p["_"],
            "message": p.get("메시지", ""),
            "caution": p.get("주의", ""),
        })
        item = {"code": code, "grade": grade if grade in GRADES else "E2"}
        # 유형 기본문과 다르면 그 동을 두고 쓴 문장이다. 그것만 동에 싣는다.
        if j["_"] != common:
            item["own"] = j["_"]
        if len(real.split()) > 2:
            item["district"] = real.split()[2]          # 성남시 분당구 같은 일반구
        # 행정동 이름(방배2동 등)은 사이트에서 법정동으로 옮겼으니 싣지 않는다.
        if "행정동 명칭" in ev:
            continue
        dongs[f"{sido}/{gusi}/{dong}"] = item

    # --- 우선 검토군 --------------------------------------------------------
    pri_tbl = next(t for t in tbls if t[0][:3] == ["구분", "대표 생활권", "판단"])
    groups = []
    for label, areas, note in pri_tbl[1:]:
        members = []
        for token in re.split(r"\s*[/·]\s*", areas):
            token = token.strip()
            if not token:
                continue
            wanted = AREA_ALIAS.get(token, [token])
            name = lambda k: k.split("/")[2]
            # '별내'는 별내동(신도시)과 별내면(외곽)이 다 있다. 동이 있으면 동만 잡고,
            # 없을 때만 읍·면으로 찾는다(수동면·하성면).
            found = [k for k in dongs
                     if any(name(k) == w or re.fullmatch(re.escape(w) + r"동(\d가)?", name(k)) for w in wanted)]
            if not found:
                found = [k for k in dongs if any(re.fullmatch(re.escape(w) + r"(면|읍)", name(k)) for w in wanted)]
            if not found:
                print(f"  ! 우선 검토군 이름을 못 찾음: {token}", file=sys.stderr)
            members.extend(found)
        groups.append({"label": label, "areas": areas, "note": note, "dongs": sorted(set(members))})
        for k in members:
            dongs[k]["group"] = label

    payload = {
        "title": "영어학원 개원시장 동별 분석",
        "as_of": "2026-09-16",
        # 판단은 읽는 사람 몫이다. 문서의 성격만 밝히고 무엇을 하라고 쓰지 않는다.
        "caution": ("동별 실측 조사가 아닙니다. 대부분의 동은 같은 유형의 대표 지역과 공식 제도를 바탕으로 "
                    "추정했고, 학원 홍보자료를 근거로 쓴 곳이 많습니다."),
        "grades": GRADES,
        "types": types,
        "groups": groups,
        "non_leveled": NON_LEVELED,
        "dongs": dongs,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    from collections import Counter
    print(f"저장: {OUT.relative_to(ROOT)}  ({OUT.stat().st_size / 1024:.0f} KB)")
    print(f"  원본 {total}행 / 중복 {dup_rows} / 구역·명칭 정정 {fixed_rows} / 실은 동 {len(dongs)}")
    print(f"  유형 {dict(Counter(d['code'] for d in dongs.values()))}")
    print(f"  등급 {dict(Counter(d['grade'] for d in dongs.values()))}  동만의 문장 {sum('own' in d for d in dongs.values())}")
    for g in groups:
        print(f"  [{g['label']}] {len(g['dongs'])}곳: {', '.join(k.split('/', 1)[1] for k in g['dongs'])}")


if __name__ == "__main__":
    main()
