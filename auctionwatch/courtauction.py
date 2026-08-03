"""법원경매정보(courtauction.go.kr) 비공식 API 클라이언트.

신규 사이트(2024 개편, WebSquare 기반)의 JSON 엔드포인트를 사용한다.
- 물건 검색:   POST /pgj/pgjsearch/searchControllerMain.on
- 물건 상세:   POST /pgj/pgj15B/selectAuctnCsSrchRslt.on
- 현황조사서:  POST /pgj/pgj15B/selectCurstExmndc.on

세션 쿠키(JSESSIONID, WMONID)가 필요하므로 첫 요청 전에 index.on 을 GET 한다.
비정상 페이로드/과도한 요청은 서버가 IP 차단 메시지를 반환하므로
요청 간격(request_interval_sec)을 반드시 지킨다.
"""

import logging
import time
from datetime import date, timedelta

import requests

log = logging.getLogger(__name__)

MAX_RETRY = 3          # 총 시도 횟수 (차단 연장 위험 때문에 적게)
RETRY_BASE_SEC = 10    # 10s → 20s 대기

# 사이트는 IP 단위 봇 차단이 공격적이다. 공개된 관측치로 30초에 16회 정도면
# 1시간 차단되므로, 요청 간격은 2초 이상을 권장한다.
MIN_INTERVAL_SEC = 2.0

# 검색 pageSize 상한 — 이 엔드포인트에서 실측한 값이다(2026-08 확인).
#   20 / 40 / 50 → HTTP 200,  100 → HTTP 400
# 외부 문서에는 10/20/50/100 이 허용값이라고 적혀 있으나 우리 조건에서는
# 100 이 거부되므로, 검증된 상한(50)을 기준으로 삼는다.
MAX_PAGE_SIZE = 50


BASE = "https://www.courtauction.go.kr"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# 용도 코드: 건물 > 주거용건물 > 아파트
USAGE_LCL = "20000"
USAGE_MCL = "20100"
USAGE_SCL = "20104"


class CourtAuctionError(RuntimeError):
    pass


class CourtAuctionBlocked(CourtAuctionError):
    """IP 차단(data.ipcheck=false). 재시도하면 차단이 연장되므로 즉시 중단한다."""


class CourtAuctionClient:
    def __init__(self, interval_sec: float = MIN_INTERVAL_SEC):
        self.sess = self._new_session()
        self.interval = max(interval_sec, MIN_INTERVAL_SEC)
        self._last_req = 0.0
        # 세션(쿠키) 발급도 네트워크가 준비되기 전이면 실패할 수 있어 재시도한다
        for attempt in range(MAX_RETRY):
            try:
                self._init_session()
                return
            except requests.RequestException as e:
                if attempt == MAX_RETRY - 1:
                    raise
                wait = RETRY_BASE_SEC * (2 ** attempt)
                log.warning("세션 발급 실패(%s/%s) — %ss 후 재시도: %s",
                            attempt + 1, MAX_RETRY, wait, type(e).__name__)
                time.sleep(wait)

    @staticmethod
    def _new_session():
        s = requests.Session()
        s.headers.update({
            "User-Agent": UA,
            "Accept": "application/json",
            "Referer": f"{BASE}/pgj/index.on",
        })
        return s

    def _init_session(self):
        r = self.sess.get(f"{BASE}/pgj/index.on", timeout=30)
        r.raise_for_status()

    def _throttle(self):
        wait = self.interval - (time.time() - self._last_req)
        if wait > 0:
            time.sleep(wait)
        self._last_req = time.time()

    def _post(self, path: str, payload: dict) -> dict:
        """법원 서버는 연결을 임의로 끊거나(reset) 일시적으로 DNS가 안 잡히는
        경우가 있다. 자동 실행에서 한 번의 일시 오류로 전체가 죽지 않도록
        지수 백오프로 재시도한다."""
        last_err = None
        for attempt in range(MAX_RETRY):
            self._throttle()
            try:
                r = self.sess.post(
                    f"{BASE}{path}",
                    json=payload,
                    headers={"Content-Type": "application/json;charset=UTF-8"},
                    timeout=60,
                )
                r.raise_for_status()
                body = r.json()
                # IP 차단은 HTTP 200 + data.ipcheck=false 로 온다. 재시도하면
                # 차단 기간이 연장되므로 예외로 즉시 중단한다.
                if (body.get("data") or {}).get("ipcheck") is False:
                    raise CourtAuctionBlocked(
                        "법원경매정보가 이 IP를 차단했습니다(ipcheck=false). "
                        "약 1시간 후 자연 복구되며, 그 사이 재시도하면 차단이 연장될 수 있습니다. "
                        "요청 간격(crawler.request_interval_sec)을 늘리고 잠시 후 다시 실행하세요.")
                break
            except (requests.ConnectionError, requests.Timeout,
                    requests.HTTPError, ValueError) as e:
                last_err = e
                if attempt == MAX_RETRY - 1:
                    raise
                wait = RETRY_BASE_SEC * (2 ** attempt)
                log.warning("%s 요청 실패(%s/%s) — %ss 후 재시도: %s",
                            path, attempt + 1, MAX_RETRY, wait, type(e).__name__)
                time.sleep(wait)
                # 끊긴 세션을 버리고 새로 만든다 (쿠키 재발급 포함)
                try:
                    self.sess.close()
                except Exception:
                    pass
                self.sess = self._new_session()
                try:
                    self._init_session()
                except requests.RequestException:
                    pass
        else:  # pragma: no cover - 위 break/raise 로 도달하지 않음
            raise last_err
        if body.get("errors"):
            raise CourtAuctionError(f"{path}: {body['errors']}")
        msg = body.get("message", "")
        if "차단" in msg or "비정상" in msg:
            raise CourtAuctionError(f"{path}: 서버 보안정책 차단 응답 — {msg}")
        return body

    def search_apartments(self, max_failed_bids: int = 1, window_days: int = 14,
                          page_size: int = 20, max_pages: int = 30,
                          min_area_m2: float = 0,
                          min_bid_price: int = 0, max_bid_price: int = 0):
        """매각기일이 [오늘, 오늘+window_days] 인 아파트 물건을 전부 페이징 수집.

        유찰횟수·면적·가격 필터는 서버측에서 적용된다.
        """
        if page_size > MAX_PAGE_SIZE:
            log.warning("pageSize %s 는 서버가 HTTP 400 으로 거절하므로 %s 로 조정합니다",
                        page_size, MAX_PAGE_SIZE)
            page_size = MAX_PAGE_SIZE
        today = date.today()
        begin = today.strftime("%Y%m%d")
        end = (today + timedelta(days=window_days)).strftime("%Y%m%d")

        items = []
        page = 1
        total = None
        while page <= max_pages:
            payload = {
                "dma_pageInfo": {
                    "pageNo": page, "pageSize": page_size, "bfPageNo": "",
                    "startRowNo": 1, "totalCnt": total or "", "totalYn": "Y" if total is None else "N",
                    "groupTotalCount": "",
                },
                "dma_srchGdsDtlSrchInfo": {
                    "rletDspslSpcCondCd": "", "bidDvsCd": "000331",
                    "mvprpRletDvsCd": "00031R", "cortAuctnSrchCondCd": "0004601",
                    "rprsAdongSdCd": "", "rprsAdongSggCd": "", "rprsAdongEmdCd": "",
                    "rdnmSdCd": "", "rdnmSggCd": "", "rdnmNo": "",
                    "mvprpDspslPlcAdongSdCd": "", "mvprpDspslPlcAdongSggCd": "",
                    "mvprpDspslPlcAdongEmdCd": "", "rdDspslPlcAdongSdCd": "",
                    "rdDspslPlcAdongSggCd": "", "rdDspslPlcAdongEmdCd": "",
                    "cortOfcCd": "", "jdbnCd": "", "execrOfcDvsCd": "",
                    "lclDspslGdsLstUsgCd": USAGE_LCL,
                    "mclDspslGdsLstUsgCd": USAGE_MCL,
                    "sclDspslGdsLstUsgCd": USAGE_SCL,
                    "cortAuctnMbrsId": "", "aeeEvlAmtMin": "", "aeeEvlAmtMax": "",
                    "lwsDspslPrcRateMin": "", "lwsDspslPrcRateMax": "",
                    "flbdNcntMin": "", "flbdNcntMax": str(max_failed_bids),
                    "objctArDtsMin": str(min_area_m2) if min_area_m2 else "",
                    "objctArDtsMax": "",
                    "mvprpArtclKndCd": "", "mvprpArtclNm": "", "mvprpAtchmPlcTypCd": "",
                    "notifyLoc": "off", "lafjOrderBy": "", "pgmId": "PGJ151F01",
                    "csNo": "", "cortStDvs": "1", "statNum": 1,
                    "bidBgngYmd": begin, "bidEndYmd": end,
                    "dspslDxdyYmd": "", "fstDspslHm": "", "scndDspslHm": "",
                    "thrdDspslHm": "", "fothDspslHm": "", "dspslPlcNm": "",
                    "lwsDspslPrcMin": str(min_bid_price) if min_bid_price else "",
                    "lwsDspslPrcMax": str(max_bid_price) if max_bid_price else "",
                    "grbxTypCd": "", "gdsVendNm": "", "fuelKndCd": "",
                    "carMdyrMax": "", "carMdyrMin": "", "carMdlNm": "", "sideDvsCd": "",
                },
            }
            body = self._post("/pgj/pgjsearch/searchControllerMain.on", payload)
            data = body.get("data", {})
            rows = data.get("dlt_srchResult") or []
            info = data.get("dma_pageInfo", {})
            total = int(info.get("totalCnt") or 0)
            items.extend(rows)
            if page * page_size >= total or not rows:
                break
            page += 1
        return items

    def get_detail(self, cort_ofc_cd: str, cs_no: str, gds_seq) -> dict:
        """물건상세 — 매각물건명세서 요약(비고/최선순위/배당요구종기 등) 포함."""
        payload = {"dma_srchGdsDtlSrch": {
            "csNo": cs_no, "cortOfcCd": cort_ofc_cd,
            "dspslGdsSeq": str(gds_seq), "pgmId": "PGJ15BM01", "srchInfo": "",
        }}
        body = self._post("/pgj/pgj15B/selectAuctnCsSrchRslt.on", payload)
        return (body.get("data") or {}).get("dma_result") or {}

    def get_current_state_report(self, cort_ofc_cd: str, user_cs_no: str) -> dict:
        """현황조사서 — 임대차(점유) 관계 목록 포함. user_cs_no 는 '2008타경25092' 형식."""
        payload = {"dma_srchCurstExmn": {
            "cortOfcCd": cort_ofc_cd, "csNo": user_cs_no,
            "auctnInfOriginDvsCd": "2", "ordTsCnt": "",
        }}
        body = self._post("/pgj/pgj15B/selectCurstExmndc.on", payload)
        return body.get("data") or {}


# 매각기일 결과 코드 — 사이트에서 관측된 값
DXDY_RESULT = {
    "000": "진행", "001": "매각", "002": "유찰", "003": "변경",
    "004": "연기", "005": "취하", "006": "정지", "007": "기각",
}
DXDY_KIND = {"01": "매각기일", "02": "매각결정기일"}


def parse_bid_history(detail: dict):
    """상세조회의 gdsDspslDxdyLst → 기일별 이력.

    유찰이 언제·얼마에 났는지가 여기 있다. 유찰 횟수만 보는 것보다
    '어느 가격대에서 안 팔렸는지'를 알 수 있어 판단에 직접 쓰인다.
    """
    rows = (detail or {}).get("gdsDspslDxdyLst") or []
    out = []
    for r in rows:
        if DXDY_KIND.get(r.get("auctnDxdyKndCd")) != "매각기일":
            continue  # 매각결정기일은 제외
        out.append({
            "date": r.get("dxdyYmd"),
            "time": r.get("dxdyHm"),
            "place": r.get("dxdyPlcNm"),
            "min_price": r.get("tsLwsDspslPrc") or None,
            "sold_amount": r.get("dspslAmt") or None,
            "result": DXDY_RESULT.get(r.get("auctnDxdyRsltCd")) if r.get("auctnDxdyRsltCd") else None,
        })
    return out or None


def parse_case_flags(detail: dict):
    """사건 진행상 주의 신호.

    근거가 확실한 필드만 쓴다. `auctnSuspStatCd` 는 '00' 외에 '04' 등도
    정상 진행 물건에서 관측되어(정지사유 없음·진행상태 정상) 코드 의미가
    불분명하므로 단독 판단에 쓰지 않는다 — 추측으로 경고를 만들면
    사용자가 정상 물건을 걸러버린다.
    """
    cs = (detail or {}).get("csBaseInfo") or {}
    flags = []
    if cs.get("csProgSuspRsn"):
        flags.append(("경매 정지", "danger",
                      f"사건 진행이 정지된 상태입니다(사유: {cs['csProgSuspRsn']}). "
                      f"기일이 진행되지 않을 수 있으니 법원에 확인하세요."))
    if cs.get("rletApalYn") == "Y":
        flags.append(("항고 제기", "warn",
                      "매각허가결정에 항고가 제기됐습니다. 확정이 늦어져 대금납부·"
                      "소유권 이전 일정이 밀릴 수 있습니다."))
    if cs.get("csUltmtYmd"):
        flags.append(("사건 종국", "danger",
                      f"사건이 {cs['csUltmtYmd']}에 종국 처리됐습니다. 진행 여부를 반드시 확인하세요."))
    # 기일 이력에 '매각' 뒤 새 기일이 또 있으면 = 낙찰자 대금 미납 → 재매각
    hist = parse_bid_history(detail) or []
    for i, h in enumerate(hist[:-1]):
        if h.get("result") == "매각" and any(x.get("result") is None for x in hist[i + 1:]):
            flags.append(("재매각(대금 미납)", "warn",
                          f"{h['date'][:4]}.{h['date'][4:6]}.{h['date'][6:]}에 "
                          f"{(h.get('sold_amount') or h.get('min_price') or 0)/1e8:.2f}억으로 낙찰됐으나 "
                          f"낙찰자가 대금을 내지 않아 다시 경매에 나왔습니다. 입찰보증금이 "
                          f"20~30%로 올라가는 경우가 많고, 미납 사유(자금 문제인지 숨은 하자인지)를 "
                          f"확인해야 합니다."))
            break
    return flags or None
