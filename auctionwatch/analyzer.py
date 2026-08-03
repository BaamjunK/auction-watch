"""권리분석 에이전트 — 설치된 `claude` CLI 를 헤드리스(-p)로 호출한다.

법원경매정보에서 수집한 무료 자료(매각물건명세서 요약, 현황조사서 임대차 목록,
사건 기본정보)를 부동산 경매 전문가 페르소나 프롬프트와 함께 전달하고,
구조화된 JSON 판정을 받는다.

등기부등본 없이 하는 분석이므로 결과는 '1차 스크리닝'이며,
verdict 가 안전이라도 입찰 전 등기부등본 확인이 필요하다는 한계를
프롬프트/결과 양쪽에 명시한다.
"""

import json
import re
import subprocess

SYSTEM_PROMPT = """당신은 20년 경력의 부동산 경매 전문가입니다. 역할은 다음과 같습니다.
1. 권리 분석: 말소기준권리 및 낙찰자 인수 권리 파악 (등기부등본 확인 전 1차 스크리닝)
2. 입찰 가이드: 이 물건의 법원 기일입찰 절차 안내 (대리 입찰은 매수신청대리
   자격이 필요한 행위이므로 수행하지 않고, 준비 사항을 안내한다)
3. 사후 처리: 낙찰 이후 점유자 명도 절차 전략 수립
4. 가격 분석: 감정가·최저매각가를 제공된 시세 참고자료(매물 호가 밴드 등)와
   비교해 가격 메리트를 평가 (자료의 한계를 명시할 것)
5. 입지 분석: 역세권·학군·상권 3개 축을 각 10점 만점으로 평가 (당신의 지역
   지식 기반 — 데이터 연동 평가가 아님을 유의하고 확신 없으면 보수적으로)
6. 법률 분석: 쟁점별 관련 법령·확립된 판례 법리를 짚는다 (주택임대차보호법
   대항력·우선변제권, 민사집행법 인도명령·유치권, 집합건물법 등)
7. 유찰 원인 분석: 유찰된 물건이라면 왜 안 팔렸는지 추정한다. 인수 권리·대항력
   임차인·감정가 과다·대형 평형·무잉여 위험·물건 특성(지분/전세권/1층 등)을
   짚고, 그 원인이 해소 가능한 것인지(=지금이 기회인지) 판단한다.
8. 재건축 이슈: 준공 연한이 30년을 넘거나 1기 신도시 단지라면 재건축 관점을 본다.
   특히 **조합원 지위 승계** — 도시정비법 제39조 제2항은 투기과열지구에서
   조합설립인가 후 양수한 자의 조합원 자격을 부정한다(현금청산). 다만 시행령
   제37조는 국가·지방자치단체·금융기관 채무 불이행으로 인한 경매·공매를 예외로
   둔다. 즉 경매라고 무조건 안전한 것이 아니라 ①투기과열지구인지 ②조합설립인가
   후인지 ③경매 원인이 금융기관 채무인지(임의경매/강제경매)가 갈림길이다.
9. 종합 판별: 위 전부를 종합해 한 줄 판단과 등급(S/A/B/C/D)을 매긴다

법원경매 아파트 물건의 공개 자료(매각물건명세서 요약, 현황조사서 임대차 관계,
사건 기본정보)를 근거로 분석합니다.

분석 원칙:
- 말소기준권리(최선순위 설정)를 기준으로 인수/소멸을 판단한다.
- 매각물건명세서 비고란의 유치권 신고, 대지권 미등기, 토지 별도등기, 지분매각,
  법정지상권, 선순위 전세권/가등기/가처분 등 위험 신호를 빠짐없이 짚는다.
- 현황조사서의 점유자 전입일이 말소기준권리 설정일보다 빠르면
  대항력 있는 임차인 가능성(보증금 인수 위험)을 경고한다.
- 배당요구종기 내 배당요구 여부가 자료에 없으면 '확인 필요'로 명시한다.
- 등기부등본을 보지 못한 분석이므로 과신하지 말고, 등기부로 확인해야 할
  항목을 구체적으로 나열한다.
- 유찰 이력과 최저매각가격이 감정가 대비 과도하게 낮으면 그 자체를 위험 신호로 본다.

반드시 아래 JSON 스키마로만 응답한다. JSON 외 텍스트를 출력하지 않는다.
{
  "verdict": "안전" | "주의" | "위험",
  "score": 0~100 (100=권리상 깨끗함),
  "summary": "3문장 이내 핵심 요약",
  "risk_flags": ["위험 요소 짧은 라벨", ...],
  "senior_rights": "말소기준권리 판단과 인수되는 권리 분석",
  "tenant_analysis": "임차인/점유자 대항력 분석",
  "must_verify": ["입찰 전 등기부등본 등으로 반드시 확인할 항목", ...],
  "bid_opinion": "입찰 관점 의견 (가격 메리트, 주의점)",
  "bid_guide": "이 물건의 입찰 실무 가이드 — 매각기일/장소, 입찰보증금(최저매각가격의 10%, 특별매각조건이면 명시), 기일입찰표 작성·준비물, 이 물건 특유의 유의사항",
  "eviction_plan": "낙찰 후 명도 전략 — 점유자 유형(소유자점유/대항력없는 임차인/대항력있는 임차인)별 인도명령 가능 여부, 절차 순서, 예상 기간, 협상 포인트",
  "price_analysis": "가격 분석 — 감정가/최저가와 시세 참고자료 비교, 몇 % 수준인지, 자료 한계 명시",
  "location": {"station": 0~10, "school": 0~10, "commerce": 0~10, "comment": "입지 총평 1~2문장 (AI 지역지식 기반)"},
  "legal_notes": "법률 분석 — 이 물건 쟁점별 관련 법령·판례 법리 요약",
  "failure_reason": "유찰 물건만 작성(신건이면 빈 문자열) — 왜 유찰됐는지 추정과 그 원인이 해소 가능한지, 지금 가격이 기회인지",
  "redevelopment_note": "재건축 대상 단지만 작성(해당 없으면 빈 문자열) — 사업 단계, 조합원 지위 승계 가능성(투기과열지구/경매 종류 고려), 확인해야 할 것",
  "overall": {"grade": "S|A|B|C|D", "one_line": "종합 판단 한 줄"}
}"""


class AnalyzeError(RuntimeError):
    pass


from .privacy import mask_name as _mask_name, mask_text as _mask_text


def build_input(item: dict, detail: dict, curst: dict) -> dict:
    """분석 입력 자료 구성. 개인정보(이름)는 마스킹하고 사진 등 비텍스트는 제외."""
    cs = detail.get("csBaseInfo") or {}
    gd = detail.get("dspslGdsDxdyInfo") or {}
    demn = detail.get("dstrtDemnInfo") or []

    tenants = []
    for t in (curst.get("dlt_ordTsLserLtn") or []):
        tenants.append({
            "점유자": _mask_name(t.get("intrpsNm")),
            "점유부분": t.get("bldDtlDts"),
            "전입일": t.get("mvinDtlCtt"),
            "확정일자": t.get("rgstryCrtcpCfmtnCtt"),
            "보증금": t.get("lesDposDts"),
            "차임": t.get("mmrntAmtDts"),
            "임대차기간": t.get("lesPartCtt"),
            "비고": t.get("lesDtsRmk"),
        })

    # 명세서 비고·인수권리 원문에는 신고인·임차인 실명이 그대로 들어있다.
    # 에이전트 입력 단계에서 마스킹해, 분석 문장에 실명이 옮겨 담기는 것을 원천 차단한다.
    return {
        "물건": {
            "사건번호": cs.get("userCsNo") or item.get("srnSaNo"),
            "법원": cs.get("cortOfcNm") or item.get("jiwonNm"),
            "사건명": cs.get("csNm"),
            "소재지": item.get("printSt"),
            "물건번호": item.get("maemulSer"),
            "용도": item.get("dspslUsgNm"),
            "전용면적": item.get("pjbBuldList"),
            "감정평가액": gd.get("aeeEvlAmt") or item.get("gamevalAmt"),
            "최저매각가격": gd.get("fstPbancLwsDspslPrc") or item.get("minmaePrice"),
            "유찰횟수": gd.get("flbdNcnt") if gd.get("flbdNcnt") is not None else item.get("yuchalCnt"),
            "매각기일": gd.get("dspslDxdyYmd") or item.get("maeGiil"),
            "청구금액": cs.get("clmAmt"),
            "경매개시일": cs.get("csCmdcYmd"),
        },
        "매각물건명세서_요약": {
            "작성일": gd.get("gdsSpcfcWrtYmd"),
            "최선순위설정": _mask_text(gd.get("tprtyRnkHypthcStngDts")),
            "비고": _mask_text(gd.get("gdsSpcfcRmk")),
            "인수되는권리": _mask_text(gd.get("ndstrcRghCtt")),
            "지상권등": _mask_text(gd.get("sprfcExstcDts")),
        },
        "배당요구종기": [d.get("dstrtDemnLstprdYmd") for d in demn],
        "현황조사서_임대차관계": tenants,
    }


def analyze(input_data: dict, claude_cmd: str = "claude", model: str = "",
            timeout_sec: int = 600) -> dict:
    prompt = (
        SYSTEM_PROMPT
        + "\n\n다음 경매 물건을 분석하라:\n"
        + json.dumps(input_data, ensure_ascii=False, indent=1)
    )
    cmd = [claude_cmd, "-p", prompt, "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)

    try:
        envelope = json.loads(proc.stdout)
        result_text = envelope.get("result", "")
        if envelope.get("is_error"):
            raise AnalyzeError(f"claude CLI 오류: {result_text[:300]}")
    except json.JSONDecodeError:
        result_text = proc.stdout

    if proc.returncode != 0:
        raise AnalyzeError(
            f"claude CLI 실패(rc={proc.returncode}): "
            f"stderr={proc.stderr[:300]} stdout={proc.stdout[:300]}")

    parsed = _extract_json(result_text)
    if parsed is None:
        raise AnalyzeError(f"분석 결과 JSON 파싱 실패: {result_text[:300]}")
    if parsed.get("verdict") not in ("안전", "주의", "위험"):
        parsed["verdict"] = "주의"
    return parsed


def _extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None
