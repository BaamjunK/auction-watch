"""권리 자동 체크리스트 — 수집 데이터 기반 결정적(deterministic) 룰 엔진.

LLM 분석과 별개로, 매각물건명세서 요약·현황조사서에서 기계적으로 탐지 가능한
위험 신호를 ok/warn/danger 체크리스트로 만든다. 대시보드에 그대로 표시되고
분석 에이전트 입력에도 포함된다.
"""

import re
from datetime import date

# 투기과열지구 — 이 지역에서만 조합원 지위 승계 제한이 걸린다.
# 2023년 1월 이후 강남·서초·송파·용산 4곳만 유지되고 있으나, 지정은 수시로
# 바뀌므로 판정 문구에 '확인 필요'를 함께 남긴다.
SPECULATIVE_ZONES = ("강남구", "서초구", "송파구", "용산구")

# 1기 신도시 — 노후계획도시 특별법 대상. 재건축 기대가 가격에 반영되는 지역.
FIRST_GEN_NEWTOWNS = {
    "성남시 분당구": "분당", "고양시 일산동구": "일산", "고양시 일산서구": "일산",
    "안양시 동안구": "평촌", "군포시": "산본", "부천시": "중동",
}
REBUILD_AGE = 30  # 재건축 연한 (주택법 시행령상 준공 후 30년)

_DATE = re.compile(r"(\d{4})[.\-/년\s]*(\d{1,2})[.\-/월\s]*(\d{1,2})")


def _parse_date(text):
    if not text:
        return None
    m = _DATE.search(str(text))
    if not m:
        return None
    y, mo, d = (int(g) for g in m.groups())
    if not (1980 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return y * 10000 + mo * 100 + d


def _building_age(use_date):
    """'1986.10.06.' → 준공 후 경과 연수. 알 수 없으면 None."""
    m = re.match(r"(\d{4})", str(use_date or ""))
    return date.today().year - int(m.group(1)) if m else None


def build_redevelopment(addr, kapt_name, use_date, case_name):
    """재건축 관련 자동 판정.

    핵심은 조합원 지위 승계다. 도시정비법 제39조 제2항은 **투기과열지구에서
    조합설립인가 후** 양수한 자를 조합원으로 인정하지 않는다(현금청산 대상).
    다만 시행령 제37조에 따라 '국가·지방자치단체·금융기관에 대한 채무를
    이행하지 못해 경매·공매되는 경우'는 예외다. 즉 경매라고 무조건 안전한 게
    아니라, **경매 원인이 금융기관 채무인지**가 갈림길이다.

    반환: {age, is_old, zone, newtown, checks:[...]} — 해당 없으면 None.
    """
    age = _building_age(use_date)
    addr = addr or ""
    zone = next((z for z in SPECULATIVE_ZONES if z in addr), None)
    # 1기 신도시는 1991~1996년 준공이라 반드시 노후 단지다. 준공 25년 미만이면
    # 같은 행정구역이라도 2기 이후 신도시로 본다(분당구 안의 판교 등).
    newtown = next((v for k, v in FIRST_GEN_NEWTOWNS.items() if k in addr), None)
    if newtown and age is not None and age < 25:
        newtown = None
    name = kapt_name or ""
    # 단지명에서 재건축 추진 신호 (주공·시가지 등은 노후 단지에 흔하다)
    name_hint = bool(re.search(r"주공|시가지|저층|연립", name)) and (age is None or age >= 25)

    if not (age and age >= REBUILD_AGE) and not newtown and not name_hint:
        return None  # 재건축 이슈를 논할 단계가 아님

    checks = []

    def add(label, status, note):
        checks.append({"label": label, "status": status, "note": note})

    if age is not None:
        if age >= REBUILD_AGE:
            add("재건축 연한", "warn",
                f"준공 {age}년차 — 재건축 연한(30년) 경과. 사업 단계에 따라 가치와 "
                f"권리관계가 크게 달라지므로 조합 설립 여부를 확인해야 합니다.")
        else:
            add("재건축 연한", "ok", f"준공 {age}년차 — 연한(30년) 미도달")
    else:
        add("재건축 연한", "warn",
            "준공연도를 확인하지 못했습니다. 노후 단지로 보이므로 건축물대장에서 "
            "사용승인일을 직접 확인하세요.")

    if newtown:
        add("1기 신도시", "warn",
            f"{newtown} — 노후계획도시 특별법 대상 지역입니다. 선도지구 지정 여부에 따라 "
            f"기대가 가격에 이미 반영돼 있을 수 있어, 실거래가와 비교해 프리미엄을 "
            f"얼마나 주고 사는지 따져야 합니다.")

    # 조합원 지위 승계 — 가장 중요한 판정
    is_voluntary = "임의" in (case_name or "")   # 임의경매 = 담보(근저당) 실행
    if zone:
        if is_voluntary:
            add("조합원 지위 승계", "warn",
                f"{zone}는 투기과열지구입니다(지정 현황은 변동되므로 확인 필요). 조합설립인가 "
                f"후에 취득하면 원칙적으로 조합원이 될 수 없어 현금청산 대상이 됩니다. "
                f"다만 이 물건은 임의경매(담보 실행)로, 금융기관 채무 불이행에 따른 경매라면 "
                f"시행령상 예외에 해당해 승계가 인정될 수 있습니다. ① 조합설립인가 여부 "
                f"② 경매 신청 채권자가 금융기관인지 두 가지를 반드시 확인하세요.")
        else:
            add("조합원 지위 승계", "danger",
                f"{zone}는 투기과열지구인데 이 물건은 강제경매입니다. 조합설립인가 후 취득이면 "
                f"조합원 자격이 부정돼 현금청산될 위험이 있고, 강제경매는 신청 채권자가 "
                f"금융기관이 아닐 수 있어 시행령상 예외를 못 받을 수 있습니다. 조합 단계와 "
                f"신청 채권자를 확인하기 전에는 입찰하지 마세요.")
    elif age and age >= REBUILD_AGE:
        add("조합원 지위 승계", "ok",
            "투기과열지구가 아니어서 조합원 지위 승계 제한(도시정비법 제39조 제2항)이 "
            "적용되지 않습니다. 다만 조합 정관상 별도 제약은 조합에 확인하세요.")

    return {"age": age, "is_old": bool(age and age >= REBUILD_AGE),
            "zone": zone, "newtown": newtown, "checks": checks}


def build_failure_signals(failed_bids, appraisal, min_price, area_m2,
                          claim_amount, take_over, remark, tenants, market):
    """유찰 물건의 '왜 안 팔렸나' 자동 신호. 유찰 0회면 None."""
    if not failed_bids:
        return None
    signals = []
    rate = round(min_price / appraisal * 100) if (appraisal and min_price) else None

    # 1) 인수해야 하는 권리 — 유찰의 가장 흔한 이유
    blob = f"{take_over or ''} {remark or ''}"
    if "임차권" in blob or ("보증금" in blob and "인수" in blob):
        signals.append(("인수 보증금", "danger",
                        "낙찰자가 떠안아야 할 임차보증금이 있습니다. 응찰자들이 실질 부담을 "
                        "계산하기 어려워 유찰되는 대표적인 경우입니다."))
    if "유치권" in blob:
        signals.append(("유치권 신고", "danger",
                        "유치권 주장이 있어 명도가 길어질 수 있다고 판단된 것으로 보입니다."))
    if "지분" in blob:
        signals.append(("지분 매각", "danger",
                        "지분만 매각되는 물건은 단독으로 활용할 수 없어 응찰자가 거의 없습니다."))
    if "대지권" in blob and "미등기" in blob:
        signals.append(("대지권 미등기", "warn",
                        "땅에 대한 권리가 정리되지 않아 응찰을 망설이게 만드는 요소입니다."))

    # 2) 점유자 존재
    if tenants:
        signals.append(("점유자 있음", "warn",
                        "점유자가 있어 명도 부담이 있다고 판단된 것으로 보입니다. "
                        "대항력 여부에 따라 인수 금액이 달라집니다."))

    # 3) 감정가가 시세보다 높게 잡힌 경우
    mk = market or {}
    if mk.get("asking_min") and appraisal and appraisal > mk["asking_min"] * 1.05:
        signals.append(("감정가 과다 가능성", "warn",
                        f"감정가({appraisal/1e8:.1f}억)가 단지 매물 호가 하단"
                        f"({mk['asking_min']/1e8:.1f}억)보다 높습니다. 감정 시점과 현재 "
                        f"시세 차이 때문에 첫 기일에 응찰이 없었을 수 있습니다."))

    # 4) 대형 평형 — 수요층이 얇다
    if area_m2 and area_m2 >= 130:
        signals.append(("대형 평형", "warn",
                        f"전용 {area_m2:.0f}㎡ 대형은 수요층이 얇아 유찰이 잦습니다. "
                        f"가격이 더 내려갈 여지가 있다는 뜻이기도 합니다."))

    # 5) 청구금액 과다 — 무잉여로 취소될 수 있어 응찰을 꺼린다
    if claim_amount and min_price and claim_amount >= min_price * 0.95:
        signals.append(("청구금액 과다", "warn",
                        f"청구금액({claim_amount/1e8:.1f}억)이 최저가에 육박해, 더 유찰되면 "
                        f"남을 게 없다는 이유로 경매가 취소될 수 있습니다."))

    if not signals:
        signals.append(("특이 사유 없음", "ok",
                        "권리·가격 면에서 뚜렷한 결함이 보이지 않습니다. 첫 기일 감정가가 "
                        "부담스러웠거나 관심이 적었던 경우로, 오히려 가격이 내려온 지금이 "
                        "기회일 수 있습니다."))

    return {"failed_bids": failed_bids, "price_rate": rate,
            "checks": [{"label": l, "status": s, "note": n} for l, s, n in signals]}


def build_auto_checks(senior_lien, remark, take_over, tenants):
    """반환: [{"label", "status": ok|warn|danger, "note"}]"""
    checks = []
    remark = remark or ""
    take_over = take_over or ""
    blob = f"{remark} {take_over}"

    def add(label, status, note):
        checks.append({"label": label, "status": status, "note": note})

    # 1) 유치권
    if "유치권" in blob:
        add("유치권", "danger", "유치권 신고 있음 — 성립 여부 확인 전 입찰 금지 수준의 리스크")
    else:
        add("유치권", "ok", "명세서상 유치권 신고 없음")

    # 2) 전세권/임차권 인수
    if "전세권" in blob and ("매각" in blob or "인수" in blob or "말소되지" in blob):
        add("전세권", "danger", "전세권 관련 인수/매각 문구 — 명세서 원문 확인 필수")
    if "임차권" in blob:
        add("임차권등기", "danger", "주택임차권등기 인수 가능성 — 보증금·배당 확인 필수")

    # 3) 대지권
    if "대지권" in blob and ("미등기" in blob or "없" in blob):
        add("대지권", "warn", "대지권 미등기 — 분양대금 완납 여부 확인 필요")
    else:
        add("대지권", "ok", "대지권 관련 특이 기재 없음")

    # 4) 토지 별도등기
    if "별도등기" in blob:
        add("토지 별도등기", "warn", "토지 별도등기 있음 — 인수 여부 확인 필요")

    # 5) 지분/공유자
    if "우선매수" in blob or "지분" in blob:
        add("지분/공유자", "warn", "공유자 우선매수·지분 매각 가능성 — 매각 대상 범위 확인")

    # 6) 재매각/특별매각조건
    if "특별매각" in blob or re.search(r"보증금[^0-9]*20\s*%", blob) or "재매각" in blob:
        add("재매각/특별조건", "warn", "특별매각조건(보증금 상향 등) — 전 낙찰자 미납 사유 탐문")

    # 7) 말소기준권리 성격
    sl = senior_lien or ""
    if "압류" in sl or "개시결정" in sl or "가압류" in sl:
        add("말소기준권리", "warn", f"말소기준이 담보권이 아님({sl.strip()}) — 선순위 등기 정밀 확인")
    elif sl:
        add("말소기준권리", "ok", f"최선순위 설정: {sl.strip()}")
    else:
        add("말소기준권리", "warn", "최선순위 설정 정보 없음 — 명세서 원문 확인")

    # 8) 점유자 대항력 (전입일 vs 말소기준일)
    base = _parse_date(sl)
    tenants = tenants or []
    if not tenants:
        add("점유자", "ok", "현황조사상 임대차 관계 없음 (소유자 점유 추정)")
    else:
        worst, note = "ok", ""
        for t in tenants:
            moved = _parse_date(t.get("전입일"))
            if moved is None or base is None:
                worst = "warn" if worst == "ok" else worst
                note = note or "점유자 전입일 또는 말소기준일 미상 — 전입세대열람 필요"
            elif moved < base:
                worst = "danger"
                note = f"전입({t.get('전입일')})이 말소기준({sl.strip()})보다 빠름 — 대항력 가능성"
                break
            elif moved == base:
                worst = "warn" if worst == "ok" else worst
                note = "전입일=말소기준 설정일 — 대항력은 익일 발생 원칙이나 등기부로 확인"
            else:
                note = note or f"전입({t.get('전입일')})이 말소기준보다 늦음 — 대항력 없음"
        add("점유자 대항력", worst, note)

    # 9) 면적/건축물대장 불일치
    if "면적" in remark and ("불일치" in remark or "다르" in remark or "등재되어 있으나" in remark):
        add("면적 표기", "warn", "등기부·건축물대장 면적 불일치 기재 — 감정평가서 확인")

    return checks
