# -*- coding: utf-8 -*-
"""실거래가를 동별 요약과 아파트 단지 목록으로 정리한다.

아파트  단지 하나를 지도 핀 하나로 삼는다. 거래가 여러 건이면 ㎡당 가격의
        중간값으로 대표한다. 평수가 달라도 단지끼리 견줄 수 있어야 해서다.
상가    학원이 들어갈 수 있는 제2종근린생활 위주로 동별 시세와 용도지역을 낸다.
        거래가 드문드문해 개별 위치보다 동 단위 요약이 쓸모 있다.

입력  data/raw/realestate_apt_2026-08.csv
      data/raw/realestate_nrg_2026-08.csv
출력  data/geo/apt_complexes.csv   (좌표 변환 대상: 단지명 + 동)
      web/data/realestate.json     (동별 요약)
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
APT_SRC = ROOT / "data/raw/realestate_apt_2026-08.csv"
NRG_SRC = ROOT / "data/raw/realestate_nrg_2026-08.csv"
COMPLEX_OUT = ROOT / "data/geo/apt_complexes.csv"
SHOP_OUT = ROOT / "data/geo/nrg_buildings.csv"
SUMMARY_OUT = ROOT / "web/data/realestate.json"

SIDO_BY_PREFIX = {"11": "서울", "41": "경기"}
# 학원·교습소가 들어갈 수 있는 건물 용도
ACADEMY_USE = ("제1종근린생활", "제2종근린생활")


def money(series: pd.Series) -> pd.Series:
    """'255,000' (만원) -> 2550000000 (원)"""
    return pd.to_numeric(series.astype(str).str.replace(",", "").str.strip(),
                         errors="coerce") * 10_000


def sgg_names() -> dict[str, str]:
    """시군구 코드 -> 이름. 아파트 자료엔 이름 칸이 없어 상가 자료에서 가져온다."""
    df = pd.read_csv(NRG_SRC, dtype=str, usecols=["sggCd", "sggNm"]).fillna("")
    return {r.sggCd: r.sggNm.split()[0].strip()
            for r in df.itertuples() if r.sggCd and r.sggNm}


def base(df: pd.DataFrame, names: dict[str, str]) -> pd.DataFrame:
    df = df.copy()
    df["시도"] = df["sggCd"].astype(str).str[:2].map(SIDO_BY_PREFIX)
    df["구시"] = (df["sggNm"].astype(str).str.split().str[0].str.strip()
                  if "sggNm" in df.columns else df["sggCd"].astype(str).map(names))
    df["동"] = df["umdNm"].astype(str).str.strip()
    df["금액"] = money(df["dealAmount"])
    df["연"] = pd.to_numeric(df["dealYear"], errors="coerce")
    df["월"] = pd.to_numeric(df["dealMonth"], errors="coerce")
    return df.dropna(subset=["시도", "구시", "금액"])


def load_apt(names: dict[str, str]) -> pd.DataFrame:
    df = base(pd.read_csv(APT_SRC, dtype=str).fillna(""), names)
    df["단지"] = df["aptNm"].astype(str).str.strip()
    df["면적"] = pd.to_numeric(df["excluUseAr"], errors="coerce")
    df["건축년도"] = pd.to_numeric(df["buildYear"], errors="coerce")
    df = df[(df["면적"] > 0) & (df["단지"] != "")]
    df["per_m2"] = df["금액"] / df["면적"]
    return df


def load_nrg(names: dict[str, str]) -> pd.DataFrame:
    df = base(pd.read_csv(NRG_SRC, dtype=str).fillna(""), names)
    df["면적"] = pd.to_numeric(df["buildingAr"], errors="coerce")
    df["용도"] = df["buildingUse"].astype(str).str.strip()
    df["용도지역"] = df["landUse"].astype(str).str.strip()
    df["지번"] = df["jibun"].astype(str).str.strip()
    df["건축년도"] = pd.to_numeric(df["buildYear"], errors="coerce")
    df = df[df["면적"] > 0]
    df["per_m2"] = df["금액"] / df["면적"]
    return df


def main() -> None:
    for src in (APT_SRC, NRG_SRC):
        if not src.exists():
            sys.exit(f"원본이 없습니다: {src}  (build/fetch_realestate.py 먼저)")

    names = sgg_names()
    apt, nrg = load_apt(names), load_nrg(names)

    # --- 지도에 찍을 단지 목록 -------------------------------------------------
    complexes = (apt.groupby(["시도", "구시", "동", "단지"])
                    .agg(거래수=("금액", "size"),
                         제곱미터당=("per_m2", "median"),
                         금액중간=("금액", "median"),
                         면적중간=("면적", "median"),
                         건축년도=("건축년도", "median"),
                         최근연=("연", "max"))
                    .reset_index())
    for col in ("제곱미터당", "금액중간", "건축년도"):
        complexes[col] = complexes[col].round().astype("Int64")
    complexes["면적중간"] = complexes["면적중간"].round(1)
    COMPLEX_OUT.parent.mkdir(parents=True, exist_ok=True)
    complexes.to_csv(COMPLEX_OUT, index=False, encoding="utf-8")

    # --- 지도에 찍을 상가 건물 목록 ---------------------------------------------
    # 한 건물에서 호실이 여러 번 거래되므로 지번으로 묶는다.
    shops = nrg[nrg["지번"] != ""]
    shops = (shops.groupby(["시도", "구시", "동", "지번"])
                  .agg(거래수=("금액", "size"),
                       제곱미터당=("per_m2", "median"),
                       금액중간=("금액", "median"),
                       면적중간=("면적", "median"),
                       건축년도=("건축년도", "median"),
                       용도=("용도", lambda s: s.value_counts().index[0]),
                       용도지역=("용도지역", lambda s: s.value_counts().index[0]),
                       최근연=("연", "max"))
                  .reset_index())
    for col in ("제곱미터당", "금액중간", "건축년도"):
        shops[col] = shops[col].round().astype("Int64")
    shops["면적중간"] = shops["면적중간"].round(1)
    shops.to_csv(SHOP_OUT, index=False, encoding="utf-8")

    # --- 동별 요약 -------------------------------------------------------------
    summary: dict[str, dict] = {}

    for (sido, gusi, dong), g in apt.groupby(["시도", "구시", "동"]):
        summary.setdefault(f"{sido}/{gusi}/{dong}", {})["apt"] = {
            "n": len(g),
            "per_m2": int(g["per_m2"].median()),
            "price": int(g["금액"].median()),
            "area": round(g["면적"].median(), 1),
            "complexes": int(g["단지"].nunique()),
        }

    academy_ok = nrg[nrg["용도"].str.startswith(ACADEMY_USE)]
    for (sido, gusi, dong), g in nrg.groupby(["시도", "구시", "동"]):
        room = academy_ok[(academy_ok["시도"] == sido) & (academy_ok["구시"] == gusi)
                          & (academy_ok["동"] == dong)]
        summary.setdefault(f"{sido}/{gusi}/{dong}", {})["nrg"] = {
            "n": len(g),
            "n_academy_ok": len(room),
            # 학원이 들어갈 수 있는 건물만의 시세. 없으면 전체로 대신한다.
            "per_m2": int((room if len(room) else g)["per_m2"].median()),
            "zones": (g["용도지역"].value_counts().head(4).to_dict()),
        }

    payload = {
        "base_ym": "2026-08",
        "months": 24,
        "source": "국토교통부 실거래가 (아파트 매매 · 상업업무용 매매)",
        "note": "아파트값은 그 동네 집값이지 학원 임대료가 아니다. 구매력을 가늠하는 용도로만 읽는다.",
        "dongs": summary,
    }
    SUMMARY_OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                           encoding="utf-8")

    print(f"저장: {COMPLEX_OUT.relative_to(ROOT)}  단지 {len(complexes):,}개")
    print(f"저장: {SHOP_OUT.relative_to(ROOT)}  상가 건물 {len(shops):,}개")
    print(f"저장: {SUMMARY_OUT.relative_to(ROOT)}  동 {len(summary):,}개 "
          f"({SUMMARY_OUT.stat().st_size/1024:.0f} KB)")
    print(f"  아파트 거래 {len(apt):,}건 / 상업업무용 {len(nrg):,}건 "
          f"(그중 1·2종근생 {len(academy_ok):,}건)")


if __name__ == "__main__":
    main()
