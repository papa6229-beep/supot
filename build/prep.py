# -*- coding: utf-8 -*-
"""공공데이터 원본 CSV -> 화면이 읽는 지역별 집계 JSON

입력  data/raw/aca_2026-08.csv      NEIS 학원교습소정보 월 스냅샷 (CP949)
      data/raw/school_2026-08.csv   NEIS 학교기본정보 월 스냅샷 (CP949)
      data/raw/pop_2026-08.csv      행안부 법정동별 연령별 인구 (fetch_population.py)
      data/raw/dongmap.csv          행정동-법정동 연계표 (prep_dongmap.py)
출력  web/data/regions.json

지역 키는 (시도, 구·시, 법정동). 학원·학교 원본에 좌표가 없어 주소에서 동을 뽑고,
연계정보의 실제 동 이름 목록으로 검증한다. 인구도 법정동 기준으로 받아 그대로 맞물린다.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ACA_SRC = ROOT / "data/raw/aca_2026-08.csv"
# 학교알리미 2026 공시: 학년별 재학생, 전입·전출 (build/fetch_schoolinfo.py)
SCHOOLINFO_SRC = ROOT / "data/raw/schoolinfo_2026.json"
# 3년 전 같은 날 스냅샷. 새로 생긴 곳·사라진 곳을 가르는 기준이다.
# 나이스 파일 목록에서 2023년 8월 31일 기준은 fileSeq=43 이다.
ACA_OLD_SRC = ROOT / "data/raw/aca_2023-08.csv"
OLD_YM = "2023-08"
SCH_SRC = ROOT / "data/raw/school_2026-08.csv"
POP_SRC = ROOT / "data/raw/pop_2026-08.csv"
DONGMAP_SRC = ROOT / "data/raw/dongmap.csv"
OUT = ROOT / "web/data/regions.json"

# 주민등록 인구를 학교급 나이대로 자른다 (만 나이 기준, 양끝 포함).
AGE_BANDS = {
    "pop_elem": (6, 11),      # 초등학생 나이
    "pop_mid": (12, 14),      # 중학생 나이
    "pop_target": (9, 14),    # 초등 고학년 + 중등 = 이번 사업 대상
}

BASE_YM = "2026-08"
NEW_YEARS = 3                       # '최근에 생긴 곳'으로 볼 기간
SIDO = {"서울특별시교육청": "서울", "경기도교육청": "경기"}
UNKNOWN_DONG = "(동 미상)"
# 이보다 학생이 적은 동은 목록에 올리지 않는다. 학원 자리로 볼 곳이 아니다.
MIN_POP = 100

# --- 영어 판별 ---------------------------------------------------------------
# '어학원'은 국어학원(658곳)·헤어학원·중국어학원 등을 끌고 오므로 앞글자를 배제한다.
ENG_NAME = re.compile(
    r"영어|잉글리[시쉬]|[Ee]nglish|ENGLISH|랭귀지|랭기지|ESL"
    r"|파닉스|[Pp]honics|(?<!국)(?<!헤)(?<!중국)(?<!일본)(?<!외국)어학원"
)
ENG_COURSE = re.compile(r"영어|[Ee]nglish|파닉스|리딩|리스닝|스피킹")
OTHER_LANG = re.compile(r"중국어|일본어|베트남|스페인어|프랑스어|독일어|러시아어|태국어|아랍어|한국어")
ENG_STRICT = re.compile(r"영어|잉글리[시쉬]|[Ee]nglish|ENGLISH")


def mark_english(df: pd.DataFrame) -> pd.Series:
    """학원명·교습과정·수강료 내역을 함께 보고 영어 교습 여부를 판정한다.

    교습과정명에는 '영어'라는 값이 없고 '보습' 같은 대분류만 들어와서
    한 필드만으로는 판별되지 않는다. 교습계열 '외국어'에는 중국어·일본어
    학원이 섞여 있어 단독 신호로 쓰지 않는다.

    교습소는 법으로 1과목만 가르치므로 이름이 곧 과목이다. '김보영과학교습소'
    처럼 교습과정에 '영어'가 잘못 입력된 곳이 있어 교습소는 이름 신호를 요구한다.
    """
    by_name = df["학원명"].str.contains(ENG_NAME, na=False)
    by_course = (df["교습과정목록명"].str.contains(ENG_COURSE, na=False)
                 | df["인당수강료"].str.contains(ENG_COURSE, na=False))
    other = (df["학원명"].str.contains(OTHER_LANG, na=False)
             & ~df["학원명"].str.contains(ENG_STRICT, na=False))
    is_institute = df["학원교습소명"] == "교습소"
    return ((by_name | (by_course & ~is_institute)) & ~other)


# --- 전문 / 복합 ------------------------------------------------------------
# 영어 말고 다른 교과목 신호. '외국어'의 '국어', '보습·논술'의 '논술',
# '영어독서'의 '독서'는 영어학원에도 흔해서 제외하거나 앞글자를 배제한다.
OTHER_SUBJECT = re.compile(
    r"수학|과학|사회|한문|한자|코딩|컴퓨터|미술|음악|피아노|바둑|웅변|속독|역사"
    r"|(?<!외)(?<!중)(?<!한)(?<!영)국어"
)


def mark_combined(df: pd.DataFrame) -> pd.Series:
    """영어와 다른 과목을 같이 가르치는 곳을 표시한다.

    교습소는 1과목만 가능하므로 언제나 '전문'이다.
    분야명 '종합(대)'는 종합학원이라는 뜻이 아니라 분류 코드 이름이어서
    (대치심슨어학원 같은 순수 어학원 427곳이 여기 들어간다) 신호로 쓰지 않는다.
    """
    combined = (df["학원명"].str.contains(OTHER_SUBJECT, na=False)
                | df["교습과정목록명"].str.contains(OTHER_SUBJECT, na=False))
    return combined & (df["학원교습소명"] == "학원")


# --- 주소 파싱 ---------------------------------------------------------------
DONG_TOKEN = re.compile(r"^[가-힣]+[0-9]*(동|읍|면|가)$")
DONG_HEAD = re.compile(r"^([가-힣]+[0-9]*(?:동|읍|면|가))(?:\s|$)")


def dong_candidates(detail: str) -> tuple[list[str], bool]:
    """도로명상세주소에서 동으로 보이는 토막을 등장 순서대로 모은다.

    ', 3층 (개포동, 삼성빌딩)'               -> (['개포동'], True)
    ', 206호 (산본동, 개나리상가(가동))'       -> (['산본동', '가동'], True)
    ', 2층 일부(정면)(노고산동 40-41)'        -> (['정면', '노고산동'], True)
    '골드프라자 주건축물제1동 C406호'          -> (['주건축물제1동'], False)

    괄호 안은 나이스가 법정동을 적는 칸이라 믿을 만하지만, 괄호가 없어 본문에서
    주워온 것은 '가동'·'주건축물제1동'처럼 건물 표기일 때가 많다. 어디서 왔는지를
    함께 돌려줘서 뒤에서 다르게 다룬다.

    괄호가 겹쳐 있으면(`상가(가동)`) 짝을 맞춰 찾는 방식으로는 바깥쪽 산본동을
    통째로 놓친다. 그래서 괄호 기호로 토막내고, 첫 토막만 괄호 밖으로 친다.
    """
    if not detail:
        return [], False
    chunks = re.split(r"[()]", detail)
    inside = [c for c in chunks[1:] if c.strip()]
    out = []
    for chunk in inside:
        for part in chunk.split(","):
            m = DONG_HEAD.match(part.strip())
            if m:
                out.append(m.group(1))
    if out:
        return out, True
    m = re.search(r"([가-힣]+[0-9]*(?:동|읍|면|가))(?:[,\s]|$)", detail)
    return ([m.group(1)] if m else []), False


# 건물 이름이 동 이름처럼 보이는 것들. '상가동 302호', '강촌라이프상가'가 대표적이다.
# 법정동 이름에는 이런 말이 들어가지 않으므로 통째로 걸러도 안전하다.
NOT_A_DONG = re.compile(r"상가|아파트|빌딩|타워|프라자|플라자|센터|별관|본관|신관|관리동|사무동|기숙사")

# 건물의 동 표기('가동', '에이동', '제1동', '마송타운1동'). 이름만 보면 동인지
# 건물인지 알 수 없어서, 그 구에 실제로 있는 이름일 때만 받아들인다.
# 중구 다동이나 동작구 상도1동처럼 진짜 있는 이름은 그대로 살아남는다.
BUILDING_LABEL = re.compile(r"^(?:[가-하]|에이|비|씨|디|이|제\d+|주건축물제\d+|.*\d+)동$")


def pick_dong(detail: str, known: set[str]) -> str:
    """후보 중 실제로 존재하는 동을 고른다.

    '(상가동)'처럼 아파트 상가 동호수가 앞 괄호에 오는 경우가 1천 건 넘게 있어서,
    연계정보에 있는 이름인지 확인하고 고른다.
    """
    found, from_paren = dong_candidates(detail)
    candidates = [c for c in found if not NOT_A_DONG.search(c)]
    for name in candidates:
        if name in known:
            return name
    # 퇴계원면 -> 퇴계원읍처럼 읍·면 승격으로 표기가 어긋난 경우를 한 번 더 본다.
    for name in candidates:
        for a, b in (("면", "읍"), ("읍", "면")):
            if name.endswith(a) and name[:-1] + b in known:
                return name[:-1] + b
    # 연계정보에 없어도 괄호 안 값이면 받아들인다. 오포읍이 갈라지며 생긴
    # 광주시 고산동·능평동처럼, 연계정보가 개편을 아직 못 따라온 동들이 있다.
    if from_paren:
        for name in candidates:
            if not BUILDING_LABEL.match(name):
                return name
    return UNKNOWN_DONG


def parse_gusi(road_address: str) -> str | None:
    """도로명주소에서 시·군·구를 뽑는다.

    '서울특별시 송파구 송이로 45'   -> '송파구'
    '경기도 성남시 분당구 정자일로'  -> '성남시'   (학원 데이터의 행정구역명과 맞춘다)
    '평택시 고덕국제5로 165'        -> '평택시'   (시도가 빠진 주소도 있다)
    """
    for token in (road_address or "").split()[:2]:
        if len(token) > 1 and token[-1] in "시군구" and not token.endswith("특별시") \
           and not token.endswith("광역시") and not token.endswith("자치시"):
            return token
    return None


# --- 수강료 파싱 -------------------------------------------------------------
FEE_ITEM = re.compile(r"([^:,]+):\s*(\d+)")


def fee_values(text: str) -> list[int]:
    """'문법 영어:268000, 리딩:192000' -> [268000, 192000]

    월 수강료로 보기 어려운 값(만원 미만·3백만원 초과)은 버린다.
    """
    if not text or not text.strip():
        return []
    return [v for _, a in FEE_ITEM.findall(text)
            if 10_000 <= (v := int(a)) <= 3_000_000]


# --- 로딩 --------------------------------------------------------------------
def load_academies(known: dict[tuple[str, str], set[str]], src: Path = None) -> pd.DataFrame:
    """학원 스냅샷을 읽는다. src 를 주면 과거 스냅샷을 읽는다(폐원 비교용)."""
    df = pd.read_csv(src or ACA_SRC, encoding="cp949", dtype=str, low_memory=False).fillna("")
    # 2023년 이전 스냅샷은 칸 이름이 조금 다르다.
    df = df.rename(columns={"인당수강료내용": "인당수강료", "수정일": "수정일자"})
    df = df[df["시도교육청명"].isin(SIDO)].copy()
    df["시도"] = df["시도교육청명"].map(SIDO)
    # 행정구역명이 비어 있는 곳이 48건 있어 도로명주소에서 보충한다.
    gusi = df["행정구역명"].str.strip()
    df["구시"] = gusi.where(gusi != "", df["도로명주소"].map(parse_gusi))
    df["동"] = [known.fix(s, g, pick_dong(d, known.get((s, g), set())))
                for d, s, g in zip(df["도로명상세주소"], df["시도"], df["구시"])]
    df["영어"] = mark_english(df)
    df["복합"] = mark_combined(df)
    df["개설연도"] = pd.to_numeric(df["개설일자"].str.slice(0, 4), errors="coerce")
    df = df.dropna(subset=["구시"])
    if src is None and ACA_OLD_SRC.exists():
        df = compare_with_old(df, load_academies(known, ACA_OLD_SRC))
    return df


def _same_place_names(df: pd.DataFrame) -> set:
    return set(zip(df["시도"], df["구시"], df["학원명"].str.replace(r"\s", "", regex=True)))


def compare_with_old(cur: pd.DataFrame, old: pd.DataFrame) -> pd.DataFrame:
    """3년 전 스냅샷과 학원지정번호로 맞춘다.

    학원이 이전하거나 변경 등록을 하면 개설일자가 새 날짜로 바뀐다
    (2023년 목록에 2022년 개원으로 있던 곳이 지금은 2025년 개원으로 적힌 식).
    지정번호는 그대로라서 번호로 맞추면 된다. 단, 번호는 교육청마다 따로 매겨
    서울과 경기에 같은 번호가 있다. 반드시 (시도, 번호)로 맞춘다.
      - 문 연 해: 두 목록 중 더 이른 개설일
      - 새로 생긴 곳: 3년 전 목록에 번호가 없던 곳
    같은 구에 같은 이름이 3년 전에도 있었으면 번호만 바뀐 재등록으로 보고 새로 치지 않는다.
    사라진 곳은 old_closed() 가 따로 센다.
    """
    first = old.groupby(["시도", "학원지정번호"])["개설일자"].min().to_dict()
    prev = pd.Series([first.get(k, "") for k in zip(cur["시도"], cur["학원지정번호"])], index=cur.index)
    earlier = (prev != "") & (prev < cur["개설일자"])
    cur["개설일자"] = cur["개설일자"].where(~earlier, prev)
    cur["개설연도"] = pd.to_numeric(cur["개설일자"].str.slice(0, 4), errors="coerce")

    old_names = _same_place_names(old)
    renamed = [(a, b, c.replace(" ", "")) in old_names
               for a, b, c in zip(cur["시도"], cur["구시"], cur["학원명"])]
    old_ids = set(zip(old["시도"], old["학원지정번호"]))
    seen = pd.Series([k in old_ids for k in zip(cur["시도"], cur["학원지정번호"])], index=cur.index)
    cur["신규"] = ~seen & ~pd.Series(renamed, index=cur.index)
    return cur


def old_closed(known) -> pd.DataFrame:
    """3년 전에 있던 영어 학원·교습소 중 지금 목록에 없는 곳. 3년 전 주소 기준."""
    if not ACA_OLD_SRC.exists():
        return pd.DataFrame(columns=["시도", "구시", "동"])
    old = load_academies(known, ACA_OLD_SRC)
    cur = pd.read_csv(ACA_SRC, encoding="cp949", dtype=str, low_memory=False,
                      usecols=["시도교육청명", "행정구역명", "학원지정번호", "학원명", "도로명주소"]).fillna("")
    cur = cur[cur["시도교육청명"].isin(SIDO)].copy()
    cur["시도"] = cur["시도교육청명"].map(SIDO)
    gusi = cur["행정구역명"].str.strip()
    cur["구시"] = gusi.where(gusi != "", cur["도로명주소"].map(parse_gusi))
    cur_ids = set(zip(cur["시도"], cur["학원지정번호"]))
    still = pd.Series([k in cur_ids for k in zip(old["시도"], old["학원지정번호"])], index=old.index)
    gone = old[old["영어"] & ~still]
    cur_names = _same_place_names(cur.dropna(subset=["구시"]))
    moved = [(a, b, c.replace(" ", "")) in cur_names
             for a, b, c in zip(gone["시도"], gone["구시"], gone["학원명"])]
    return gone[[not m for m in moved]]


def load_population() -> pd.DataFrame:
    """법정동별 1세 단위 인구를 나이대로 잘라 돌려준다.

    응답의 '법정구역' 칸은 이렇게 생겼다.
        '서울특별시 강남구  (1168000000)'             <- 시·군·구 합계
        '서울특별시 강남구 역삼동 (1168010100)'        <- 법정동
        '경기도 성남시 분당구 정자동 (…)'              <- 일반구가 한 단계 더 있다
        '경기도 화성시 만세구 (4159100000)'            <- 일반구 소계
        '경기도 화성시 효행구 봉담읍 상리(…)'           <- 읍·면은 리까지 쪼개져 있다

    학원 주소는 읍·면까지만 적히므로(봉담읍) 리는 읍·면으로 합쳐 올린다.
    """
    df = pd.read_csv(POP_SRC, dtype=str).fillna("")
    parts = (df["법정구역"].str.strip().str.replace(r"\s+", " ", regex=True)
             .str.extract(r"^(.*?)\s*\((\d+)\)$")[0].str.split())

    def level(p: list[str] | float) -> str | None:
        """시·군·구 아래 단계의 이름. 합계 행이면 None."""
        if not isinstance(p, list) or len(p) < 3:
            return None
        rest = [t for t in p[2:] if not t.endswith("구")]   # 일반구는 건너뛴다
        if not rest:
            return None                                     # 일반구 소계 행
        for token in rest:                                  # 리는 읍·면으로 올린다
            if token.endswith(("읍", "면")):
                return token
        return rest[-1]

    df["시도"] = parts.str[0].map({"서울특별시": "서울", "경기도": "경기"})
    df["구시"] = parts.str[1]
    df["동"] = [level(p) for p in parts]
    df = df.dropna(subset=["시도"])

    def age_col(age: int) -> str:
        return f"{BASE_YM[:4]}년{BASE_YM[5:]}월_계_{age}세"

    for name, (lo, hi) in AGE_BANDS.items():
        cols = [age_col(a) for a in range(lo, hi + 1)]
        df[name] = sum(pd.to_numeric(df[c].str.replace(",", ""), errors="coerce").fillna(0)
                       for c in cols).astype(int)

    return df[["시도", "구시", "동"] + list(AGE_BANDS)]


def load_dongmap() -> pd.DataFrame:
    """행정동 ↔ 법정동 연결표 (prep_dongmap.py 가 만든 작은 파일)."""
    df = pd.read_csv(DONGMAP_SRC, dtype=str).fillna("")
    # 구·시 자기 자신을 가리키는 행은 뺀다 ('가평군 / 가평군 / 가평군').
    return df[(df["행정동"] != df["구시"]) & (df["법정동"] != df["구시"])]


class DongBook(defaultdict):
    """구·시별로 실제 존재하는 동 이름 모음. 주소 파싱 검증에 쓴다.

    book[(시도, 구시)] 는 그 구의 행정동·법정동 이름 집합이다.
    fix() 는 파싱한 동 이름을 한 번 더 바로잡는다.
    """

    def __init__(self, dongmap: pd.DataFrame):
        super().__init__(set)
        self.legal: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.admin: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        self.where: dict[tuple[str, str], set[str]] = defaultdict(set)
        for sido, gusi, admin, legal in zip(dongmap["시도"], dongmap["구시"],
                                            dongmap["행정동"], dongmap["법정동"]):
            self[(sido, gusi)].update((admin, legal))
            self.legal[(sido, gusi)].add(legal)
            self.admin[(sido, gusi)][admin].add(legal)
            self.where[(sido, legal)].add(gusi)

    def fix(self, sido: str, gusi: str, name: str) -> str:
        if name == UNKNOWN_DONG:
            return name
        key = (sido, gusi)
        if name in self.legal[key]:
            return name
        # 행정동 이름이면 법정동으로 옮긴다. 송중동 -> 미아동.
        # 법정동이 여럿에 걸치면(청파동 -> 청파동1·2·3가, 서계동) 하나로 못 정한다.
        # 읍·면은 우리 목록의 단위 그대로라 건드리지 않는다.
        if name in self.admin[key] and not name.endswith(("읍", "면")):
            legal = self.admin[key][name]
            return next(iter(legal)) if len(legal) == 1 else UNKNOWN_DONG
        if name in self[key]:
            return name
        # 리가 동으로 바뀐 곳. 광주시 고산리 -> 고산동. 연계정보가 개편을 못 따라왔다.
        if name.endswith("동") and name[:-1] + "리" in self.legal[key]:
            return name
        # 그 구에는 없고 옆 구에 있는 이름이면 주소의 구와 동이 엇갈린 것이다.
        # 강남대로 건물이 '강남구 … (서초동)'으로 적힌 식이다. 어느 쪽이 맞는지
        # 모르니 동은 비워두고, 구 합계에만 남긴다.
        if self.where.get((sido, name), set()) - {gusi}:
            return UNKNOWN_DONG
        return name


def known_dongs(dongmap: pd.DataFrame) -> DongBook:
    return DongBook(dongmap)


def load_schools(known: dict[tuple[str, str], set[str]]) -> pd.DataFrame:
    df = pd.read_csv(SCH_SRC, encoding="cp949", dtype=str, low_memory=False).fillna("")
    df = df[df["시도교육청명"].isin(SIDO)].copy()
    # 초·중학교만. '각종학교(초)'·'평생학교' 등은 일반 학령인구 수요와 성격이 달라 제외한다.
    df = df[df["학교종류명"].isin(["초등학교", "중학교"])].copy()
    df["시도"] = df["시도교육청명"].map(SIDO)
    df["구시"] = df["도로명주소"].map(parse_gusi)
    df = df.dropna(subset=["구시"])
    df["동"] = [known.fix(s, g, pick_dong(d, known.get((s, g), set())))
                for d, s, g in zip(df["도로명상세주소"], df["시도"], df["구시"])]
    return attach_school_stats(df)


def attach_school_stats(df: pd.DataFrame) -> pd.DataFrame:
    """학교알리미 공시를 (구시, 학교명)으로 붙인다. 99% 맞는다(못 맞춘 곳은 이전·개교 예정).

    대상학생: 초등학교는 4~6학년, 중학교는 1~3학년 재학생. 인구 지표(초4~중3)와 같은 학년으로 맞춘다.
    전입·전출: 그 학년도에 다른 학교에서 옮겨 온 / 옮겨 간 학생 수.
    """
    for c in ("재학생", "대상학생", "전입", "전출"):
        df[c] = pd.NA
    if not SCHOOLINFO_SRC.exists():
        return df
    rows = json.loads(SCHOOLINFO_SRC.read_text(encoding="utf-8"))["list"]
    norm = lambda n: re.sub(r"\s", "", n)
    stats = {}
    for x in rows:
        adr = (x.get("ADRCD_NM") or "").split()
        gusi = adr[1] if len(adr) > 1 else ""
        elem = any(k.startswith("STDNT_SUM_2") for k in x)
        target = (x.get("STDNT_SUM_24", 0) + x.get("STDNT_SUM_25", 0) + x.get("STDNT_SUM_26", 0)) if elem else \
                 (x.get("STDNT_SUM_31", 0) + x.get("STDNT_SUM_32", 0) + x.get("STDNT_SUM_33", 0))
        stats[(gusi, norm(x["SCHUL_NM"]))] = (x.get("STDNT_SUM"), target, x.get("MVIN_SUM"), x.get("MVT_SUM"))
    got = [stats.get((g, norm(n))) for g, n in zip(df["구시"], df["학교명"])]
    for i, c in enumerate(("재학생", "대상학생", "전입", "전출")):
        df[c] = [v[i] if v else pd.NA for v in got]
    return df


# --- 집계 --------------------------------------------------------------------
def summarize(aca: pd.DataFrame, sch: pd.DataFrame, cutoff: int) -> dict:
    eng = aca[aca["영어"]] if len(aca) else aca
    fees = [v for text in eng.get("인당수강료", []) for v in fee_values(text)]
    return {
        "eng_total": len(eng),
        "eng_academy": int((eng["학원교습소명"] == "학원").sum()) if len(eng) else 0,
        "eng_institute": int((eng["학원교습소명"] == "교습소").sum()) if len(eng) else 0,
        "eng_solo": int(((eng["학원교습소명"] == "학원") & ~eng["복합"]).sum()) if len(eng) else 0,
        "eng_combo": int(eng["복합"].sum()) if len(eng) else 0,
        # 3년 전 목록이 있으면 번호 비교로, 없으면 개설연도로 센다.
        "eng_new3y": (int(eng["신규"].sum()) if "신규" in eng else int((eng["개설연도"] >= cutoff).sum()))
                     if len(eng) else 0,
        "all_total": len(aca),
        "fee_median": int(pd.Series(fees).median()) if fees else None,
        "sch_elem": int((sch["학교종류명"] == "초등학교").sum()) if len(sch) else 0,
        "sch_mid": int((sch["학교종류명"] == "중학교").sum()) if len(sch) else 0,
        "sch_total": len(sch),
        # 학교알리미 공시가 붙은 학교만 더한다. 하나도 없으면 비워 둔다.
        "stu_target": int(pd.to_numeric(sch["대상학생"], errors="coerce").sum()) if len(sch) and sch["대상학생"].notna().any() else None,
        "mv_net": int(pd.to_numeric(sch["전입"], errors="coerce").sum() - pd.to_numeric(sch["전출"], errors="coerce").sum())
                  if len(sch) and sch["전입"].notna().any() else None,
    }


def build(aca: pd.DataFrame, sch: pd.DataFrame, keys: list[str], cutoff: int) -> list[dict]:
    """학원과 학교를 같은 지역 키로 묶는다. 한쪽에만 있는 지역도 빠짐없이 담는다."""
    aca_groups = dict(tuple(aca.groupby(keys, sort=False)))
    sch_groups = dict(tuple(sch.groupby(keys, sort=False)))
    empty_aca = aca.iloc[0:0]
    empty_sch = sch.iloc[0:0]

    rows = []
    for key in sorted(set(aca_groups) | set(sch_groups)):
        row = summarize(aca_groups.get(key, empty_aca), sch_groups.get(key, empty_sch), cutoff)
        row["sido"] = key[0]
        row["parent"] = key[1] if len(key) == 3 else None
        row["name"] = key[-1]
        rows.append(row)
    return rows


def attach_population(rows: list[dict], sums: dict, keyer) -> int:
    """집계 결과에 인구를 붙인다. 못 붙인 행 수를 돌려준다.

    학원 주소는 '양지면'인데 인구 자료는 '양지읍'인 경우가 있다. 읍·면 승격을
    한쪽만 반영한 것이라, 동 이름을 고르던 때와 같이 여기서도 한 번 더 본다.
    """
    missing = 0
    for row in rows:
        key = keyer(row)
        band = sums.get(key)
        if band is None and isinstance(key[-1], str):
            for a, b in (("면", "읍"), ("읍", "면")):
                if key[-1].endswith(a):
                    band = sums.get(key[:-1] + (key[-1][:-1] + b,))
                    if band is not None:
                        break
        if band is None:
            missing += 1
        for name in AGE_BANDS:
            row[name] = int(band[name]) if band is not None else None
    return missing


def main() -> None:
    for src in (ACA_SRC, SCH_SRC, POP_SRC, DONGMAP_SRC):
        if not src.exists():
            sys.exit(f"원본이 없습니다: {src}")

    dongmap = load_dongmap()
    known = known_dongs(dongmap)

    aca, sch = load_academies(known), load_schools(known)
    cutoff = int(BASE_YM[:4]) - NEW_YEARS
    pop = load_population()

    gu = build(aca, sch, ["시도", "구시"], cutoff)
    dong = build(aca, sch, ["시도", "구시", "동"], cutoff)

    closed = old_closed(known)
    by_gu = closed.groupby(["시도", "구시"]).size().to_dict()
    by_dong = closed.groupby(["시도", "구시", "동"]).size().to_dict()
    for r in gu:
        r["eng_closed3y"] = int(by_gu.get((r["sido"], r["name"]), 0))
    for r in dong:
        r["eng_closed3y"] = int(by_dong.get((r["sido"], r["parent"], r["name"]), 0))
    print(f"  3년 비교({OLD_YM} -> {BASE_YM}): 새로 생긴 영어 {int(aca.loc[aca['영어'], '신규'].sum()) if '신규' in aca else '-'}곳"
          f" / 사라진 영어 {len(closed)}곳")

    bands = list(AGE_BANDS)
    gu_pop = {(r.시도, r.구시): {b: getattr(r, b) for b in bands}
              for r in pop[pop["동"].isna()].itertuples()}
    # 읍·면은 리 여러 행이 같은 키로 올라오므로 합산한다.
    dong_pop = {k: v for k, v in
                pop[pop["동"].notna()].groupby(["시도", "구시", "동"])[bands].sum()
                .to_dict("index").items()}

    no_gu = attach_population(gu, gu_pop, lambda r: (r["sido"], r["name"]))
    no_dong = attach_population(dong, dong_pop, lambda r: (r["sido"], r["parent"], r["name"]))

    matched = [r for r in dong if r["pop_target"] is not None]
    eng_matched = sum(r["eng_total"] for r in matched)
    eng_all = sum(r["eng_total"] for r in dong)

    payload = {
        "base_ym": BASE_YM,
        "sources": ["나이스 교육정보 개방포털 · 학원교습소정보",
                    "나이스 교육정보 개방포털 · 학교기본정보",
                    "행정안전부 · 주민등록 인구통계 (법정동)",
                    "국가데이터처 · 법정동 연계정보"],
        "counts": {
            "rows": len(aca),
            "english": int(aca["영어"].sum()),
            "dong_parsed": int((aca["동"] != UNKNOWN_DONG).sum()),
            "schools": len(sch),
            "dong_with_pop": len(matched),
            "dong_total": len(dong),
        },
        "gu": sorted(gu, key=lambda r: -r["eng_total"]),
        # 목록에 올리지 않는 것: 동을 못 읽어낸 학원 묶음(지역이 아니다)과
        # 학생이 거의 없는 동. 종로 관철동처럼 사무실·상가만 있는 법정동은
        # 학원 자리를 고를 때 볼 일이 없다. 인구를 못 붙인 동은 '학생이 없다'는
        # 뜻이 아니라 우리가 못 맞춘 것이라 그대로 둔다.
        "dong": sorted((r for r in dong if r["name"] != UNKNOWN_DONG
                        and not (r["pop_target"] is not None and r["pop_target"] < MIN_POP)),
                       key=lambda r: -r["eng_total"]),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    print(f"저장: {OUT.relative_to(ROOT)}  ({OUT.stat().st_size/1024:.0f} KB)")
    print(f"  학원·교습소 {len(aca):,}건 (영어 {payload['counts']['english']:,}) "
          f"/ 동 파싱 {payload['counts']['dong_parsed']/len(aca)*100:.1f}%")
    print(f"  초·중학교 {len(sch):,}개교")
    print(f"  구·시 {len(gu)}개 (인구 없는 곳 {no_gu}) / 법정동 {len(dong)}개 (인구 없는 곳 {no_dong})")
    print(f"  인구 붙은 법정동의 영어학원 비중 {eng_matched/eng_all*100:.1f}%")

if __name__ == "__main__":
    main()
