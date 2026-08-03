"""개인정보 마스킹 — 공개 배포 시 실명 노출 방지.

법원 매각물건명세서 비고란에는 유치권 신고인·임차인·소유자 실명이 원문으로
들어있다("2025.7.24.자 김민영으로부터 유치권신고서가 제출되었으나"). 대시보드를
공개 호스팅하면 그대로 노출되므로 저장·출력 전에 마스킹한다.

일반 명사 오탐(매수인·보증금 등)을 피하려고 성씨 사전 + 문맥 패턴을 함께 쓴다.
"""

import re

# 인구 다수 성씨 (2자 성은 드물어 제외 — 오탐 위험이 더 크다)
SURNAMES = (
    "김이박최정강조윤장임한오서신권황안송전홍유고문양손배백허남심노하곽성차주우구"
    "민진지엄채원천방공현함변염여추도소석선설마길위표명기반라왕금옥육인맹제모탁국어편용"
)
# 한국인 성명은 대부분 성1 + 이름2 = 3자다. 2자까지 허용하면 '기재'·'유형' 같은
# 일반 명사가 성씨로 시작할 때 오탐이 나므로(실제로 '점유자 기재가' → '기*가' 훼손
# 사례가 있었다) 신분 표기 뒤 패턴은 3자로 한정한다.
_NAME3 = rf"[{SURNAMES}][가-힣]{{2}}"
_NAME23 = rf"[{SURNAMES}][가-힣]{{1,2}}"

# "임차인 이정숙은", "소유자 최진순이" — 신분 표기 뒤에 오는 이름.
#
# 공백을 필수(\s+)로 요구하는 것이 핵심이다. 공백을 허용하지 않으면
# "임차인이라면"의 '이라면', "소유자인지가"의 '인지가'를 이름으로 오인해
# 문장을 훼손한다(실제 발생 사례).
_PAT_ROLE = re.compile(
    rf"(임차인|소유자|채무자|점유자|권리자|신청채권자|신고인|공유자)(\s+)({_NAME3})"
    r"(?=[\s은는이가의,.)]|$)"
)
# "김민영으로부터" — 사람에게만 붙는 조사가 뒤따르는 경우 (오탐이 사실상 없어 2자도 허용)
_PAT_JOSA = re.compile(rf"({_NAME23})(?=(?:으로부터|로부터|에게서|씨로부터))")

# 성씨로 시작하지만 실명이 아닌 3자 표현 — 마스킹 제외
_STOPWORDS = {
    # 경매 용어
    "매수인", "임차인", "소유자", "채무자", "점유자", "보증금", "감정평", "신고서",
    "로부터", "주장하", "저매각", "최저가", "근저당", "전세권", "유치권", "배당요",
    "권리자", "공유자", "신청인", "매각물", "명세서", "부동산", "건축물", "집합건",
    "대지권", "지상권", "임대차", "확정일", "우선변", "인수함", "미등기", "별도등",
    "우선매", "선순위", "인도명", "무잉여", "재매각", "특별매", "말소기",
    # 분석 문장에 등장하는 일반 명사
    "기재가", "기재는", "기재된", "유형별", "유형이", "유무를", "유무와", "현황은",
    "명의로", "신분과", "신분을", "정보를", "목록은", "관계가", "관계는", "여부가",
    "여부를", "여부와", "확인이", "확인을", "이름은", "이름이", "성명이", "장기간",
    "임의로", "고지된", "표기가", "표기와", "명시된", "명시적", "기준일", "기준은",
    "차임과", "차임은", "방배동", "방식이", "석연치", "설정일", "설정된",
}


def mask_name(name: str) -> str:
    """홍길동 → 홍**, 홍길 → 홍*

    성만 남기고 이름은 전부 가린다. 끝 글자를 남기는 방식(홍*동)보다
    재식별 위험이 낮다.
    """
    if not name:
        return name
    if len(name) == 1:
        return "*"
    return name[0] + "*" * (len(name) - 1)


# 과거에 쓰던 '홍*동' 형식을 '홍**' 로 통일하기 위한 패턴
_PAT_OLDMASK = re.compile(r"([가-힣])\*([가-힣])(?![가-힣])")


def mask_text(text):
    """자유 텍스트에서 실명으로 판단되는 부분만 마스킹한다."""
    if not text:
        return text
    # 구 형식(홍*동) → 신 형식(홍**) 정규화
    text = _PAT_OLDMASK.sub(lambda m: m.group(1) + "**", str(text))

    def _role(m):
        role, gap, name = m.group(1), m.group(2), m.group(3)
        if name in _STOPWORDS:
            return m.group(0)
        return f"{role}{gap}{mask_name(name)}"

    def _josa(m):
        name = m.group(1)
        return m.group(0) if name in _STOPWORDS else mask_name(name)

    out = _PAT_ROLE.sub(_role, str(text))
    return _PAT_JOSA.sub(_josa, out)


def mask_record(rec: dict) -> dict:
    """물건 레코드의 자유 텍스트 필드를 제자리 마스킹한다."""
    for field in ("remark", "senior_lien", "status_note"):
        if rec.get(field):
            rec[field] = mask_text(rec[field])
    a = rec.get("analysis")
    if isinstance(a, dict):
        for field in ("summary", "senior_rights", "tenant_analysis", "bid_opinion",
                      "bid_guide", "eviction_plan", "price_analysis", "legal_notes"):
            if a.get(field):
                a[field] = mask_text(a[field])
        if isinstance(a.get("must_verify"), list):
            a["must_verify"] = [mask_text(v) for v in a["must_verify"]]
        if isinstance(a.get("risk_flags"), list):
            a["risk_flags"] = [mask_text(v) for v in a["risk_flags"]]
        ov = a.get("overall")
        if isinstance(ov, dict) and ov.get("one_line"):
            ov["one_line"] = mask_text(ov["one_line"])
    for c in rec.get("auto_checks") or []:
        if c.get("note"):
            c["note"] = mask_text(c["note"])
    return rec
