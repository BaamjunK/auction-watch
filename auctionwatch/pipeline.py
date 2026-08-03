"""수집 → 필터 → 권리분석 → 대시보드 생성 파이프라인.

상태는 data/state.json 에 저장한다. 물건 키는 "법원코드:사건번호:물건번호".
같은 물건이라도 매각기일이 바뀌면(유찰 후 재매각 등) 재분석한다.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from . import analyzer, webgen
from .checks import build_auto_checks, build_failure_signals, build_redevelopment
from .courtauction import (CourtAuctionBlocked, CourtAuctionClient,
                           CourtAuctionError, parse_bid_history, parse_case_flags)
from .kapt import KaptClient
from .naver import NaverLandClient, extract_complex_name, extract_region_names
from .privacy import mask_record, mask_text

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("auction-watch")


def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            log.warning("state.json 파싱 실패 — 새로 시작")
    return {"items": {}}


def save_state(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def item_key(row: dict) -> str:
    return f"{row.get('boCd')}:{row.get('saNo')}:{row.get('maemulSer')}"


def run(no_analyze: bool = False, limit: Optional[int] = None):
    cfg = load_config()
    f = cfg["filters"]
    state_path = ROOT / "data" / "state.json"
    state = load_state(state_path)

    naver = NaverLandClient(ROOT / "data" / "naver_cache.json",
                            interval_sec=cfg["crawler"]["request_interval_sec"])
    kapt_key = cfg["kapt"]["service_key"] or os.environ.get(
        cfg["kapt"].get("service_key_env", "KAPT_SERVICE_KEY"), "")
    kapt = KaptClient(kapt_key, ROOT / "data" / "kapt_cache.json")
    if not kapt.enabled:
        log.info("세대수는 네이버 부동산으로 조회합니다 (K-apt 키 미설정 — 보조 조회 비활성).")

    client = CourtAuctionClient(interval_sec=cfg["crawler"]["request_interval_sec"])
    log.info("경매 물건 검색 중... (아파트, 유찰<=%s, %s일 이내 매각기일)",
             f["max_failed_bids"], f["bid_window_days"])
    rows = client.search_apartments(
        max_failed_bids=f["max_failed_bids"],
        window_days=f["bid_window_days"],
        page_size=cfg["crawler"]["page_size"],
        max_pages=cfg["crawler"]["max_pages"],
        min_area_m2=f.get("min_area_m2") or 0,
        min_bid_price=f.get("min_bid_price") or 0,
        max_bid_price=f.get("max_bid_price") or 0,
    )
    log.info("검색 결과 %d건", len(rows))

    regions = f.get("regions") or []
    if regions:
        def in_region(r):
            loc = f"{r.get('hjguSido') or ''} {r.get('hjguSigu') or ''}".strip()
            addr = r.get("printSt") or ""
            return any(loc.startswith(reg) or addr.startswith(reg) for reg in regions)
        rows = [r for r in rows if in_region(r)]
        log.info("지역 필터(%s) 적용 후 %d건", ", ".join(regions), len(rows))
    if limit:
        rows = rows[:limit]

    analyzed_this_run = 0
    transient_fail = 0
    max_analyze = cfg["analyzer"]["max_analyze_per_run"]
    seen_keys = set()

    for row in rows:
        key = item_key(row)
        seen_keys.add(key)
        prev = state["items"].get(key)
        bid_date = row.get("maeGiil") or ""

        rec = prev if prev and prev.get("bid_date") == bid_date else None
        if rec is None:
            rec = {
                "key": key,
                "court_code": row.get("boCd"),
                "cs_no": row.get("saNo"),
                "case_no": row.get("srnSaNo"),
                "gds_seq": row.get("maemulSer"),
                "court": row.get("jiwonNm"),
                "dept": row.get("jpDeptNm"),
                "addr": row.get("printSt"),
                "area": (row.get("pjbBuldList") or "").replace("\r\n", " "),
                "area_m2": _area_m2(row.get("pjbBuldList")),
                "bld_name": row.get("buldNm") or "",
                "appraisal": _num(row.get("gamevalAmt")),
                # minmaePrice 는 감정가와 같은 값이 오는 경우가 있어(유찰 물건에서 관측)
                # 공고 최저매각가격(notifyMinmaePrice1)을 우선 사용한다.
                # 상세조회 시 fstPbancLwsDspslPrc 로 최종 교정된다.
                "min_price": (_num(row.get("notifyMinmaePrice1"))
                              or _num(row.get("minmaePrice"))),
                "failed_bids": _num(row.get("yuchalCnt")) or 0,
                "bid_date": bid_date,
                "sido": row.get("hjguSido"),
                "case_name": None,  # 상세조회에서 채움 (임의/강제 구분)
                "status": "new",
            }
            state["items"][key] = rec

        # 0) 면적·가격 필터 (서버측 필터의 이중 확인)
        if rec.get("area_m2") is None:
            rec["area_m2"] = _area_m2(rec.get("area") or "")
        excl = _excluded_by(rec, f)
        if excl and rec["status"] != "analyzed":
            rec["status"] = excl
            save_state(state_path, state)
            continue

        # 1) 세대수 확인 (min_households <= 0 이면 필터 비활성화)
        if f["min_households"] <= 0 and rec["status"] in ("new", "households_unknown"):
            rec["status"] = "pending"
        elif rec.get("households") is None and rec["status"] in ("new", "households_unknown"):
            a_sido, a_sigu, a_dong = extract_region_names(rec["addr"])
            sido = row.get("hjguSido") or a_sido
            sigu = row.get("hjguSigu") or a_sigu
            dong = row.get("hjguDong") or a_dong
            # 법정동코드: 지역명 해석(정확) → 법원 데이터 코드(있으면) 순
            bjd_raw = row.get("srchHjguRdCd") or ""
            bjd = (naver.resolve_region(sido, sigu, dong)
                   or (bjd_raw if len(bjd_raw) == 10 else ""))
            lotno = row.get("daepyoLotno") or ""
            bld = rec["bld_name"] or extract_complex_name(rec["addr"], lotno)

            # 1차: 네이버 부동산 (키 불필요) → 2차: K-apt (키 있을 때만)
            info = naver.lookup(dong_name=dong, bld_name=bld, bjd_code=bjd, lotno=lotno)
            if info["households"] is None and kapt.enabled:
                info = kapt.lookup(bjd_code=bjd, dong_name=dong,
                                   lotno=lotno, bld_name=bld)
            rec["households"] = info["households"]
            rec["kapt_name"] = info["kapt_name"]
            if info.get("market"):
                rec["market"] = info["market"]
            if info["households"] is None:
                rec["status"] = "households_unknown"
                rec["status_note"] = (
                    "세대수를 확인하지 못했습니다. 단지명 매칭 실패 — "
                    "나홀로/소규모 단지이거나 소재지에 단지명이 없는 물건일 수 있습니다."
                )
            elif info["households"] < f["min_households"]:
                rec["status"] = "excluded_households"
                rec["status_note"] = f"{info['households']}세대 — 기준({f['min_households']}세대) 미달"
            else:
                rec["status"] = "pending"

        # 2) 권리분석
        if (rec["status"] == "pending" and not no_analyze
                and cfg["analyzer"]["enabled"] and analyzed_this_run < max_analyze):
            try:
                log.info("상세/현황조사 수집: %s %s", rec["case_no"], rec["addr"])
                detail = client.get_detail(rec["court_code"], rec["cs_no"], rec["gds_seq"])
                curst = {}
                try:
                    curst = client.get_current_state_report(
                        rec["court_code"], rec["case_no"].replace(" ", ""))
                except CourtAuctionError as e:
                    log.warning("현황조사서 조회 실패(%s): %s", rec["case_no"], e)

                gd = detail.get("dspslGdsDxdyInfo") or {}
                # 상세조회 값이 정본 — 검색 목록의 금액 필드를 교정한다
                if gd.get("fstPbancLwsDspslPrc"):
                    rec["min_price"] = _num(gd["fstPbancLwsDspslPrc"])
                if gd.get("aeeEvlAmt"):
                    rec["appraisal"] = _num(gd["aeeEvlAmt"])
                if gd.get("flbdNcnt") is not None:
                    rec["failed_bids"] = gd["flbdNcnt"]
                # 교정된 최저가로 가격 필터 재확인
                excl = _excluded_by(rec, f)
                if excl:
                    rec["status"] = excl
                    save_state(state_path, state)
                    continue
                # 명세서 비고에는 신고인·임차인 실명이 원문으로 들어있어 마스킹한다
                rec["senior_lien"] = mask_text(gd.get("tprtyRnkHypthcStngDts"))
                rec["remark"] = mask_text(gd.get("gdsSpcfcRmk"))
                rec["demand_deadlines"] = [
                    d.get("dstrtDemnLstprdYmd") for d in (detail.get("dstrtDemnInfo") or [])]

                log.info("권리분석 실행: %s", rec["case_no"])
                input_data = analyzer.build_input(row, detail, curst)
                rec["auto_checks"] = build_auto_checks(
                    rec["senior_lien"], rec["remark"], gd.get("ndstrcRghCtt"),
                    input_data.get("현황조사서_임대차관계"))
                cs = detail.get("csBaseInfo") or {}
                rec["case_name"] = cs.get("csNm")
                rec["bid_history"] = parse_bid_history(detail)
                # 소재지에 단지명이 없어 세대수를 못 찾은 물건은, 명세서 비고에
                # 단지명이 등장하는 경우가 있다("…파르네빌아파트 입주자 대표회의…").
                # 그 이름으로 한 번 더 세대수를 조회한다.
                if rec.get("households") is None:
                    _retry_households_from_remark(rec, naver)
                rec["case_flags"] = parse_case_flags(detail)
                rec["claim_amount"] = _num(cs.get("clmAmt"))
                rec["redevelopment"] = build_redevelopment(
                    rec["addr"], rec.get("kapt_name"),
                    (rec.get("market") or {}).get("use_date"), rec["case_name"])
                rec["failure_signals"] = build_failure_signals(
                    rec.get("failed_bids"), rec.get("appraisal"), rec.get("min_price"),
                    rec.get("area_m2"), rec.get("claim_amount"), gd.get("ndstrcRghCtt"),
                    rec.get("remark"), input_data.get("현황조사서_임대차관계"),
                    rec.get("market"))
                input_data["자동_권리체크"] = rec["auto_checks"]
                if rec.get("redevelopment"):
                    input_data["자동_재건축판정"] = rec["redevelopment"]
                if rec.get("failure_signals"):
                    input_data["자동_유찰사유신호"] = rec["failure_signals"]
                if rec.get("market"):
                    input_data["시세참고"] = {
                        "단지_매물호가_밴드": [rec["market"].get("asking_min"),
                                          rec["market"].get("asking_max")],
                        "비고": "네이버 매물 호가(전체 평형 혼합) — 전용면적별 시세 아님",
                    }
                rec["analysis"] = analyzer.analyze(
                    input_data,
                    claude_cmd=cfg["analyzer"]["claude_cmd"],
                    model=cfg["analyzer"]["model"],
                    timeout_sec=cfg["analyzer"]["timeout_sec"],
                )
                rec["status"] = "analyzed"
                rec.pop("status_note", None)
                analyzed_this_run += 1
                log.info("→ 판정: %s (%s점)", rec["analysis"]["verdict"],
                         rec["analysis"].get("score"))
            except CourtAuctionBlocked:
                raise  # 차단은 즉시 전체 중단 — 계속 호출하면 차단이 연장된다
            except Exception as e:
                # claude CLI 자체를 쓸 수 없는 상황(미로그인·미설치·타임아웃)은
                # 물건 문제가 아니라 환경 문제다. status 를 error 로 굳히면 다음
                # 실행에서 재시도되지 않으므로 pending 으로 남겨 둔다.
                if _is_transient_analyze_error(e):
                    rec["status"] = "pending"
                    rec["status_note"] = f"분석 환경 오류로 보류(다음 실행에 재시도): {e}"
                    log.warning("분석 환경 오류 — 재시도 예정 (%s): %s", rec["case_no"], e)
                    transient_fail += 1
                    if transient_fail >= 3:
                        log.error("분석 환경 오류가 %d건 연속 — 이번 실행의 분석을 중단합니다. "
                                  "`claude` CLI 로그인 상태를 확인하세요.", transient_fail)
                        no_analyze = True
                else:
                    rec["status"] = "error"
                    rec["status_note"] = f"분석 실패: {e}"
                    log.error("분석 실패 %s: %s", rec["case_no"], e)

        save_state(state_path, state)

    # 이번 검색에 없는(매각기일 지난/취하된) 물건 정리
    stale = [k for k in state["items"] if k not in seen_keys]
    for k in stale:
        del state["items"][k]
    if stale:
        log.info("종료된 물건 %d건 정리", len(stale))
    save_state(state_path, state)

    # 대시보드 생성 — 안전 물건이 위로 오도록 정렬
    grade_order = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}

    def sort_key(rec):
        order = {"analyzed": 0, "pending": 1, "households_unknown": 2, "error": 3}
        a = rec.get("analysis") or {}
        g = grade_order.get((a.get("overall") or {}).get("grade"), 9)
        return (order.get(rec["status"], 9), g, -(a.get("score") or 0),
                rec.get("bid_date") or "")

    # 기준 미달(세대수/면적) 물건은 대시보드에 표시하지 않는다 (상태에는 유지 — 재조회 방지)
    hidden = ("excluded_households", "excluded_area", "excluded_price")
    items = sorted(
        (mask_record(r) for r in state["items"].values() if r["status"] not in hidden),
        key=sort_key)
    out = ROOT / cfg["web"]["output_html"]
    webgen.generate(items, cfg, out)
    log.info("대시보드 생성 완료: %s (물건 %d건, 이번 실행 분석 %d건)",
             out, len(items), analyzed_this_run)


_TRANSIENT_MARKERS = (
    "not logged in", "please run /login", "command not found",
    "no such file or directory", "timed out", "timeout expired",
    "rate limit", "usage limit", "overloaded",
)


def _is_transient_analyze_error(e: Exception) -> bool:
    """물건 자체가 아닌 실행 환경 문제인지 판정 (재시도 대상)."""
    import subprocess
    if isinstance(e, (FileNotFoundError, subprocess.TimeoutExpired)):
        return True
    msg = str(e).lower()
    return any(m in msg for m in _TRANSIENT_MARKERS)


def _retry_households_from_remark(rec: dict, naver) -> None:
    """명세서 비고/인수권리 문구에서 '○○아파트' 를 뽑아 세대수를 재조회한다."""
    import re
    blob = f"{rec.get('remark') or ''} {rec.get('senior_lien') or ''}"
    names = re.findall(r"([가-힣A-Za-z0-9]{2,20})아파트", blob)
    if not names:
        return
    a_sido, a_sigu, a_dong = extract_region_names(rec["addr"])
    bjd = naver.resolve_region(a_sido, a_sigu, a_dong)
    if not bjd:
        return
    for nm in dict.fromkeys(names):
        try:
            info = naver.lookup(dong_name=a_dong, bld_name=nm, bjd_code=bjd)
        except Exception:
            continue
        if info.get("households"):
            rec["households"] = info["households"]
            rec["kapt_name"] = info["kapt_name"]
            if info.get("market"):
                rec["market"] = info["market"]
            log.info("명세서 비고의 단지명 '%s' 으로 세대수 확인: %s세대",
                     nm, info["households"])
            return


def _excluded_by(rec: dict, f: dict):
    """면적·가격 기준 미달이면 해당 excluded_* 상태값, 통과면 None."""
    area, price = rec.get("area_m2"), rec.get("min_price")
    if f.get("min_area_m2") and area and area < f["min_area_m2"]:
        return "excluded_area"
    if price:
        if f.get("min_bid_price") and price < f["min_bid_price"]:
            return "excluded_price"
        if f.get("max_bid_price") and price > f["max_bid_price"]:
            return "excluded_price"
    return None


def _area_m2(pjb: str):
    """물건 표시 문자열('철근콘크리트조\\r\\n67.87㎡')에서 전용면적(㎡) 추출."""
    import re
    nums = re.findall(r"(\d+(?:\.\d+)?)㎡", pjb or "")
    return max((float(n) for n in nums), default=None)


def _num(v):
    try:
        return int(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    ap = argparse.ArgumentParser(description="아파트 경매 권리분석 파이프라인")
    ap.add_argument("--no-analyze", action="store_true",
                    help="수집/필터만 수행하고 권리분석(claude 호출)은 건너뜀")
    ap.add_argument("--limit", type=int, default=None,
                    help="검색 결과 상위 N건만 처리(테스트용)")
    args = ap.parse_args()
    run(no_analyze=args.no_analyze, limit=args.limit)


if __name__ == "__main__":
    main()
