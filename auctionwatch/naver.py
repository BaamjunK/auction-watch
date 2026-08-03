"""네이버 부동산 세대수 조회 — API 키 불필요.

1차 경로 (법정동 단지 목록):
    GET m.land.naver.com/cluster/ajax/complexList?cortarNo={법정동코드}&rletTpCd=APT|JGC&page=N
    → 해당 법정동의 전체 단지 목록(단지명 hscpNm, 총세대수 totHsehCnt).
    경매 데이터의 법정동코드(10자리)를 그대로 쓰므로 동명이단지 오매칭이 없다.
    재건축 추진 단지(은마 등)는 JGC 분류에 있으므로 APT + JGC 둘 다 조회한다.
    소재지에서 뽑은 단지명을 목록과 정규화 매칭한다 (예: '선경아파트' → '선경1,2차').

2차 경로 (키워드 리다이렉트, 1차 매칭 실패 시):
    GET m.land.naver.com/search/result/{동이름 단지명} → 302 /complex/info/{단지번호}
    GET fin.land.naver.com/complexes/{단지번호} → SSR HTML의 totalHouseholdNumber.
    단지 페이지의 법정동코드를 대조해 오매칭을 걸러낸다.

주의: new.land.naver.com 의 /api/* 는 토큰 없이는 429 를 반환하므로 쓰지 않는다.
비공식 경로이므로 사이트 개편 시 조정 필요.
"""

import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
CLUSTER_URL = "https://m.land.naver.com/cluster/ajax/complexList"
REGION_URL = "https://m.land.naver.com/map/getRegionList"
SEARCH_URL = "https://m.land.naver.com/search/result/{}"
COMPLEX_URL = "https://fin.land.naver.com/complexes/{}"
ROOT_CORTAR = "0000000000"

RE_COMPLEX_NO = re.compile(r"/complex/info/(\d+)")
RE_HOUSEHOLDS = re.compile(r'totalHouseholdNumber\\?":(\d+)')
RE_BJD = re.compile(r'legalDivisionNumber\\?":\\?"(\d{10})')
RE_NAME = re.compile(r'complexName\\?":\\?"([^"\\]+)')
# 단지 상세 SSR 의 address 블록 — 지번 대조용
RE_JIBUN = re.compile(r'"jibun\\?":\\?"([0-9\-]+)')
RE_SECTOR = re.compile(r'"sector\\?":\\?"([^"\\]+)')
RE_DETAIL_NAME = re.compile(r'"result\\?":\{\\?"name\\?":\\?"([^"\\]+)')
RE_DONGCNT = re.compile(r'"dongCount\\?":(\d+)')

PAGE_SIZE = 20  # complexList 고정 페이지 크기
MAX_PAGES = 30


def _json_or_raise(r):
    """비JSON 응답(차단 페이지 등)을 RequestException 으로 통일."""
    try:
        return r.json()
    except ValueError as e:
        raise requests.RequestException(f"비JSON 응답 (차단 가능성): {r.text[:80]!r}") from e


def _parse_price(s):
    """'15<em ...>억</em> 5,000' / '9억 8,000' / '25,000' → 원 단위 int."""
    if not s:
        return None
    text = re.sub(r"<[^>]+>", "", str(s)).replace(",", "").strip()
    m = re.match(r"(?:(\d+)억)?\s*(\d+)?", text)
    if not m or (not m.group(1) and not m.group(2)):
        return None
    eok = int(m.group(1) or 0)
    man = int(m.group(2) or 0)
    won = eok * 100_000_000 + man * 10_000
    return won or None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _village_token(bld_name: str) -> str:
    """'한솔마을 205동' → '한솔', '은평뉴타운 상림마을' → '상림' 같은 대표 토큰.

    분당·뉴타운 물건은 소재지에 마을명만 있고 네이버에는 '한솔마을주공4단지'
    처럼 등록돼 있어, 마을명 어간으로 후보를 좁히는 데 쓴다.
    """
    # 공백 토큰 중 '~마을'이 있으면 그것의 어간 (뒤쪽 우선 — '은평뉴타운 상림마을' → '상림')
    for tok in reversed((bld_name or "").split()):
        m = re.fullmatch(r"([가-힣]{2,4})마을", tok)
        if m:
            return m.group(1)
    n = _norm(bld_name)
    m = re.search(r"([가-힣]{2,4})마을", n)
    if m:
        return m.group(1)
    m = re.search(r"([가-힣]{2,4})(?:뉴타운|지구|촌)", n)
    if m:
        return m.group(1)
    return n[:3] if len(n) >= 3 else n


def _norm(name: str) -> str:
    """단지명 정규화: 공백/괄호 부가정보 제거, '아파트' 접미 제거."""
    s = re.sub(r"\([^)]*\)", "", name or "")
    s = re.sub(r"[\s·.\-]", "", s)
    s = re.sub(r"아파트$", "", s)
    return s


class NaverLandClient:
    def __init__(self, cache_path: Path, interval_sec: float = 1.5):
        self.cache_path = cache_path
        self.interval = interval_sec
        self._last = 0.0
        self.sess = requests.Session()
        self.sess.headers.update({
            "User-Agent": UA,
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://m.land.naver.com/",
        })
        self.cache = {}
        if cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    def _save(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")

    def _throttle(self):
        wait = self.interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    # ── 지역명 → 법정동코드 해석 ─────────────────────────────────────
    #
    # 법원경매 데이터의 srchHjguRdCd 가 비어 있는 물건(도로명 표기 등)이 있고,
    # 법원 자체 행정코드는 행자부 법정동코드와 체계가 달라 그대로 못 쓴다.
    # 네이버 지역 트리 API(getRegionList)로 시도→시군구→동 이름을 코드로 푼다.

    def _region_children(self, code: str):
        key = f"region:{code}"
        if key in self.cache:
            return self.cache[key]
        self._throttle()
        r = self.sess.get(REGION_URL, params={"cortarNo": code},
                          headers={"Accept": "application/json"}, timeout=20)
        r.raise_for_status()
        rows = ((_json_or_raise(r).get("result") or {}).get("list")) or []
        out = [{"name": c.get("CortarNm"), "code": c.get("CortarNo")} for c in rows]
        if out:  # 차단/오류로 빈 응답이면 캐시하지 않음
            self.cache[key] = out
            self._save()
        return out

    def resolve_region(self, sido: str, sigu: str, dong: str):
        """('서울특별시','성북구','정릉동') → '1129013300'. 실패 시 None."""
        if not (sido and sigu and dong):
            return None
        key = f"bjd:{sido}|{sigu}|{dong}"
        if key in self.cache:
            return self.cache[key]
        result = None
        try:
            # 시도: '서울특별시'→'서울' vs 네이버 '서울시'→'서울'
            sido_key = re.sub(r"(특별자치|특별|광역)?(시|도)$", "", sido.replace(" ", ""))
            sido_code = next(
                (c["code"] for c in self._region_children(ROOT_CORTAR)
                 if sido_key and sido_key in re.sub(
                     r"(특별자치|특별|광역)?(시|도)$", "", (c["name"] or "").replace(" ", ""))),
                None)
            if sido_code:
                # 시군구: '성남시분당구' vs '성남시 분당구' — 공백 제거 비교
                sigu_key = sigu.replace(" ", "")
                sigu_code = next(
                    (c["code"] for c in self._region_children(sido_code)
                     if (c["name"] or "").replace(" ", "") == sigu_key),
                    None)
                if sigu_code:
                    result = next(
                        (c["code"] for c in self._region_children(sigu_code)
                         if c["name"] == dong),
                        None)
        except requests.RequestException:
            return None  # 일시 오류는 캐시하지 않음
        if result is not None:  # 해석 실패(None)는 캐시하지 않음 — 차단 중일 수 있음
            self.cache[key] = result
            self._save()
        return result

    # ── 1차: 법정동 단지 목록 ──────────────────────────────────────────

    def list_complexes(self, bjd_code: str):
        key = f"cortar2:{bjd_code}"
        if key in self.cache:
            return self.cache[key]
        out = []
        for tp in ("APT", "JGC"):
            for page in range(1, MAX_PAGES + 1):
                self._throttle()
                r = self.sess.get(CLUSTER_URL, params={
                    "cortarNo": bjd_code, "rletTpCd": tp, "page": page,
                }, headers={"Accept": "application/json"}, timeout=20)
                r.raise_for_status()
                rows = _json_or_raise(r).get("result") or []
                for c in rows:
                    out.append({
                        "complex_no": c.get("hscpNo"),
                        "name": c.get("hscpNm"),
                        "households": c.get("totHsehCnt"),
                        "type": c.get("hscpTypeNm"),
                        "use_date": c.get("useAprvYmd"),
                        "asking_min": _parse_price(c.get("dealPrcMin")),
                        "asking_max": _parse_price(c.get("dealPrcMax")),
                        "deal_count": c.get("dealCnt"),
                        "area_min": _to_float(c.get("minSpc")),
                        "area_max": _to_float(c.get("maxSpc")),
                    })
                if len(rows) < PAGE_SIZE:
                    break
        if out:  # 차단/오류로 빈 목록이면 캐시하지 않음 (정상 빈 동은 드묾)
            self.cache[key] = out
            self._save()
        return out

    @staticmethod
    def _match(bld_name: str, complexes: list, dong_name: str = ""):
        """정규화 단지명 매칭. (score, candidate) 최고점 — 동점이면 세대수 큰 쪽.

        경매 소재지는 '행당동대림아파트', 네이버는 '행당대림'처럼 동 이름 표기가
        다른 경우가 많아, 동 이름을 제거한 변형끼리도 비교한다.
        """
        dong_stub = (dong_name or "").replace(" ", "")
        strips = [s for s in (dong_stub, dong_stub[:-1] if dong_stub.endswith("동") else "")
                  if len(s) >= 2]

        def variants(name):
            n = _norm(name)
            vs = {n}
            for s in strips:
                if n.startswith(s) and len(n) - len(s) >= 2:
                    vs.add(n[len(s):])
            return {v for v in vs if len(v) >= 2}

        targets = variants(bld_name)
        if not targets:
            return None
        best = None
        for c in complexes:
            cands = variants(c.get("name") or "")
            if not cands:
                continue
            score = 0
            for t in targets:
                for cn in cands:
                    if cn == t:
                        score = max(score, 3)
                    elif cn.startswith(t) or t.startswith(cn):
                        score = max(score, 2)
                    elif t in cn or cn in t:
                        score = max(score, 1)
            if not score:
                continue
            hh = c.get("households") or 0
            if best is None or (score, hh) > (best[0], best[1].get("households") or 0):
                best = (score, c)
        return best[1] if best else None

    # ── 2차: 키워드 리다이렉트 ────────────────────────────────────────

    def _search(self, keyword: str):
        self._throttle()
        r = self.sess.get(SEARCH_URL.format(quote(keyword)),
                          allow_redirects=False, timeout=20)
        if r.status_code in (301, 302):
            m = RE_COMPLEX_NO.search(r.headers.get("Location", ""))
            if m:
                return m.group(1)
        return None

    def _complex_info(self, complex_no: str):
        """단지 상세 — 세대수·지번·법정동코드·동수. complex_no 키로 캐시."""
        key = f"detail:{complex_no}"
        if key in self.cache:
            return self.cache[key]
        self._throttle()
        r = self.sess.get(COMPLEX_URL.format(complex_no), timeout=30)
        if r.status_code != 200:
            return None
        html = r.text
        hh = RE_HOUSEHOLDS.search(html)
        if not hh:
            return None  # 차단/구조 변경 — 캐시하지 않음
        bjd = RE_BJD.search(html)
        name = RE_DETAIL_NAME.search(html) or RE_NAME.search(html)
        jibun = RE_JIBUN.search(html)
        sector = RE_SECTOR.search(html)
        dongs = RE_DONGCNT.search(html)
        info = {
            "households": int(hh.group(1)),
            "bjd": bjd.group(1) if bjd else None,
            "name": name.group(1) if name else None,
            "jibun": jibun.group(1) if jibun else None,
            "sector": sector.group(1) if sector else None,
            "dong_count": int(dongs.group(1)) if dongs else None,
        }
        self.cache[key] = info
        self._save()
        return info

    # ── 지번 대조 매칭 (지도앱에서 주소로 확인하는 것과 동등) ─────────

    def lookup_by_jibun(self, bjd_code: str, dong_name: str, lotno: str,
                        bld_name: str = "", max_probes: int = 12):
        """법정동 단지 목록의 각 단지 상세를 열어 지번이 일치하는 단지를 찾는다.

        단지명 표기가 달라도(마을명만 있는 분당·뉴타운 물건 등) 주소가 같으면 잡힌다.
        요청 수를 줄이려고 (1) 단지명 토큰이 겹치는 후보 → (2) 나머지 순으로
        최대 max_probes 개만 조회한다. 상세 결과는 캐시되어 재실행 시 무료.
        """
        none = {"households": None, "kapt_name": None, "matched_by": None}
        if not (bjd_code and len(bjd_code) == 10 and lotno):
            return none
        try:
            complexes = self.list_complexes(bjd_code)
        except requests.RequestException:
            return none
        if not complexes:
            return none

        target = _norm(bld_name)
        token = _village_token(bld_name)

        def affinity(c):
            n = _norm(c.get("name") or "")
            if not n:
                return 0
            if token and token in n:
                return 3            # 마을명/단지명 토큰 일치 — 최우선
            if target and (target in n or n in target):
                return 2
            return 1

        ordered = sorted(complexes, key=lambda c: -affinity(c))
        lot_main = lotno.split("-")[0]

        for c in ordered[:max_probes]:
            cno = c.get("complex_no")
            if not cno:
                continue
            try:
                info = self._complex_info(cno)
            except requests.RequestException:
                break               # 차단 시 즉시 중단
            if not info or not info.get("jibun"):
                continue
            # 지번 완전 일치만 인정. 물건 지번에 부번이 없을 때만 본번 일치를 허용한다
            # (부번이 다르면 인접 필지의 다른 단지일 수 있어 오매칭 위험).
            exact = info["jibun"] == lotno
            main_ok = "-" not in lotno and info["jibun"].split("-")[0] == lot_main
            if exact or main_ok:
                if info.get("bjd") and info["bjd"] != bjd_code:
                    continue        # 법정동 불일치 — 다른 단지
                return {"households": info["households"],
                        "kapt_name": info["name"] or c.get("name"),
                        "matched_by": f"지번 대조({info['sector'] or dong_name} {info['jibun']})",
                        "market": {"asking_min": c.get("asking_min"),
                                   "asking_max": c.get("asking_max"),
                                   "deal_count": c.get("deal_count"),
                                   "use_date": c.get("use_date"),
                                   "complex_no": cno}}
        return none

    # ── 공개 인터페이스 ──────────────────────────────────────────────

    def lookup(self, dong_name: str, bld_name: str, bjd_code: str, lotno: str = ""):
        """세대수 조회. 반환: {households, kapt_name(매칭 단지명), matched_by}.

        1) 법정동 단지목록 + 단지명 매칭 (요청 1회, 캐시)
        2) 지번 대조 — 단지 상세의 address.jibun 과 물건 지번 비교 (표기 달라도 잡힘)
        3) 키워드 검색 리다이렉트
        """
        none = {"households": None, "kapt_name": None, "matched_by": None}
        if not (bld_name or lotno):
            return none

        # 1차: 법정동 단지 목록에서 단지명 매칭
        if bjd_code and len(bjd_code) == 10:
            try:
                hit = self._match(bld_name, self.list_complexes(bjd_code), dong_name)
                if hit and hit.get("households"):
                    return {"households": hit["households"],
                            "kapt_name": hit["name"],
                            "matched_by": "네이버 단지목록",
                            "market": {
                                "asking_min": hit.get("asking_min"),
                                "asking_max": hit.get("asking_max"),
                                "deal_count": hit.get("deal_count"),
                                "use_date": hit.get("use_date"),
                                "complex_no": hit.get("complex_no"),
                            }}
            except requests.RequestException:
                pass

        # 2차: 지번 대조 — 단지명 표기가 달라도 주소가 같으면 잡힌다
        if lotno:
            hit = self.lookup_by_jibun(bjd_code, dong_name, lotno, bld_name)
            if hit["households"]:
                return hit

        # 3차: 키워드 검색 리다이렉트
        keyword = f"{dong_name} {bld_name}".strip()
        kw_key = f"kw:{keyword}"
        if kw_key in self.cache:
            return self.cache[kw_key]
        result = none
        try:
            complex_no = self._search(keyword)
            if complex_no:
                info = self._complex_info(complex_no)
                if info and (not bjd_code or not info["bjd"] or info["bjd"] == bjd_code):
                    result = {"households": info["households"],
                              "kapt_name": info["name"] or bld_name,
                              "matched_by": "네이버 키워드"}
        except requests.RequestException:
            return none  # 일시 오류는 캐시하지 않음
        self.cache[kw_key] = result
        self._save()
        return result


def extract_region_names(print_st: str):
    """소재지 문자열에서 (시도, 시군구, 동) 이름 추출.

    '경기도 성남시 분당구 장미로 55 ... (야탑동,장미마을)' → ('경기도','성남시 분당구','야탑동')
    지번 주소는 세 번째 토큰이 동이고, 도로명 주소는 괄호 안에서 동을 얻는다.
    """
    if not print_st:
        return ("", "", "")
    tokens = print_st.split()
    sido = tokens[0] if tokens else ""
    sigu, dong = "", ""
    rest = tokens[1:]
    if rest:
        if len(rest) >= 2 and rest[0].endswith("시") and rest[1].endswith("구"):
            sigu = f"{rest[0]} {rest[1]}"
            rest = rest[2:]
        else:
            sigu = rest[0]
            rest = rest[1:]
    if rest and re.match(r"^[가-힣0-9]+(동|가|리)\d*$", rest[0]):
        dong = rest[0]
    if not dong:
        m = re.search(r"\(([가-힣0-9]+(?:동\d*가?|가|리))\s*,", print_st)
        if m:
            dong = m.group(1)
    return (sido, sigu, dong)


def extract_complex_name(print_st: str, lotno: str) -> str:
    """경매 소재지 문자열에서 단지명 추출.

    예: '서울특별시 중구 신당동 842 약수하이츠 104동 7층701호' + lotno '842'
        → '약수하이츠'
    도로명 형식 '... (도곡동,삼성아파트)' 는 괄호 안 단지명을 쓴다.
    """
    if not print_st:
        return ""
    m = re.search(r"\(([가-힣0-9]+동\d*가?)\s*,\s*([^)]+)\)", print_st)
    if m:
        return m.group(2).strip()
    tokens = print_st.split()
    try:
        idx = next(i for i, t in enumerate(tokens) if lotno and t.startswith(lotno))
    except StopIteration:
        return ""
    name_tokens = []
    for t in tokens[idx + 1:]:
        if re.match(r"^(제?\d+동|\d+층|\d+호|지하\d*층?|비\d+호?)", t):
            break
        name_tokens.append(t)
    return " ".join(name_tokens).strip()
