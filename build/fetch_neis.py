# -*- coding: utf-8 -*-
"""나이스 교육정보 개방포털에서 학원·학교 월 스냅샷 CSV를 받는다.

포털이 2021년 1월부터 매달 스냅샷을 쌓아두고 있어서, 최신분뿐 아니라
과거분도 같은 방식으로 받을 수 있다. 과거분을 여러 개 받아 학원지정번호로
맞춰보면 개원·폐원 추이를 낼 수 있다(현재 스냅샷에는 '개원'만 들어 있다).

사용:
    python build/fetch_neis.py              # 최신분(fileSeq 기본값)
    python build/fetch_neis.py 99           # 다른 시점의 스냅샷
"""
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENDPOINT = "https://open.neis.go.kr/portal/data/file/downloadBlobFileData.do"

# infId: 데이터셋 식별자 / infSeq=3: 파일 탭 / fileSeq: 스냅샷 시점
DATASETS = {
    "aca": ("OPEN19220231012134453534385", "학원교습소정보"),
    "school": ("OPEN17020190531110010104913", "학교기본정보"),
}
DEFAULT_FILE_SEQ = 103          # 2026년 8월 31일 기준
BASE_YM = "2026-08"


def fetch(name: str, inf_id: str, file_seq: int, out: Path) -> None:
    url = f"{ENDPOINT}?infId={inf_id}&infSeq=3&fileSeq={file_seq}"
    with urllib.request.urlopen(url, timeout=600) as r:
        data = r.read()
    if len(data) < 10_000:
        sys.exit(f"{name}: 받은 내용이 너무 작습니다 ({len(data)}B). fileSeq를 확인하세요.")
    out.write_bytes(data)
    print(f"  {out.name}  {len(data)/1024/1024:.1f} MB")


def main(file_seq: int) -> None:
    raw = ROOT / "data/raw"
    raw.mkdir(parents=True, exist_ok=True)
    print(f"나이스 스냅샷 내려받기 (fileSeq={file_seq})")
    for key, (inf_id, label) in DATASETS.items():
        fetch(label, inf_id, file_seq, raw / f"{key}_{BASE_YM}.csv")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FILE_SEQ)
