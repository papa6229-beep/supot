# -*- coding: utf-8 -*-
"""국가데이터처 「법정동 연계정보」에서 서울·경기 최신분만 추려 작은 파일로 남긴다.

원본이 82MB이고 2024년부터의 개정 이력이 전부 들어 있어서, 최신 개정일자의
서울·경기 행만 뽑아 두면 3천여 행으로 줄어든다.

사용:  python build/prep_dongmap.py "C:/.../국가데이터처_법정동 연계정보_20250602.csv"
출력:  data/raw/dongmap.csv   (시도, 구시, 행정동, 법정동)
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/raw/dongmap.csv"
SIDO = {"서울특별시": "서울", "경기도": "경기"}


def main(src: str) -> None:
    df = pd.read_csv(src, encoding="cp949", dtype=str, low_memory=False)
    df = df[df["시도명"].isin(SIDO)].copy()
    df = df[df["개정일자"] == df["개정일자"].max()]

    df["시도"] = df["시도명"].map(SIDO)
    # 학원 데이터의 행정구역명 표기에 맞춘다: '성남시 분당구' -> '성남시'
    df["구시"] = df["시군구명"].str.split().str[0]
    out = (df[["시도", "구시", "행정동명", "법정동명"]]
           .rename(columns={"행정동명": "행정동", "법정동명": "법정동"})
           .drop_duplicates()
           .sort_values(["시도", "구시", "행정동", "법정동"]))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False, encoding="utf-8")
    print(f"저장: {OUT.relative_to(ROOT)}  {len(out):,}행")
    print(f"  구·시 {out['구시'].nunique()}개 / 행정동 {out['행정동'].nunique():,}개 "
          f"/ 법정동 {out['법정동'].nunique():,}개")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("사용: python build/prep_dongmap.py <법정동 연계정보 CSV 경로>")
    main(sys.argv[1])
