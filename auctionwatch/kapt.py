"""공동주택(K-apt) 세대수 조회 — 공공데이터포털 국토교통부 API 사용.

사용 API (모두 무료, 활용신청 후 serviceKey 발급):
- 공동주택 단지 목록제공 서비스: AptListService3/getLegaldongAptList3 (법정동코드 → 단지 목록)
- 공동주택 기본 정보제공 서비스: AptBasisInfoServiceV3/getAphusBassInfoV3 (kaptCode → 세대수 kaptdaCnt)

serviceKey 가 없으면 모든 조회가 None(미확인)을 반환한다.
결과는 data/kapt_cache.json 에 캐시한다(법정동코드 목록 + 단지 세대수).
"""

import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

LIST_URL = "https://apis.data.go.kr/1613000/AptListService3/getLegaldongAptList3"
BASIS_URL = "https://apis.data.go.kr/1613000/AptBasisInfoServiceV3/getAphusBassInfoV3"


def _parse_items(resp: requests.Response):
    """data.go.kr 응답을 JSON/XML 어느 쪽이든 item 리스트로 정규화."""
    text = resp.text.strip()
    if text.startswith("{"):
        body = resp.json()
        items = (((body.get("response") or {}).get("body") or {}).get("items")) or []
        if isinstance(items, dict):
            items = items.get("item") or []
        if isinstance(items, dict):
            items = [items]
        return items
    root = ET.fromstring(text)
    out = []
    for item in root.iter("item"):
        out.append({child.tag: (child.text or "").strip() for child in item})
    return out


class KaptClient:
    def __init__(self, service_key: str, cache_path: Path):
        self.key = service_key or ""
        self.cache_path = cache_path
        self.cache = {"dong": {}, "basis": {}}
        if cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def _save(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")

    def _list_by_dong(self, bjd_code: str):
        if bjd_code in self.cache["dong"]:
            return self.cache["dong"][bjd_code]
        params = {
            "serviceKey": self.key, "bjdCode": bjd_code,
            "numOfRows": "500", "pageNo": "1", "_type": "json",
        }
        r = requests.get(LIST_URL, params=params, timeout=30)
        r.raise_for_status()
        items = _parse_items(r)
        result = [{"kaptCode": i.get("kaptCode"), "kaptName": i.get("kaptName")} for i in items]
        self.cache["dong"][bjd_code] = result
        self._save()
        return result

    def _basis(self, kapt_code: str):
        if kapt_code in self.cache["basis"]:
            return self.cache["basis"][kapt_code]
        params = {"serviceKey": self.key, "kaptCode": kapt_code, "_type": "json"}
        r = requests.get(BASIS_URL, params=params, timeout=30)
        r.raise_for_status()
        items = _parse_items(r)
        info = items[0] if items else {}
        result = {
            "kaptName": info.get("kaptName"),
            "kaptAddr": info.get("kaptAddr"),
            "households": _to_int(info.get("kaptdaCnt")),
            "dong_count": _to_int(info.get("kaptDongCnt") or info.get("kaptdongCnt")),
            "use_date": info.get("kaptUsedate"),
        }
        self.cache["basis"][kapt_code] = result
        self._save()
        return result

    def lookup(self, bjd_code: str, dong_name: str, lotno: str, bld_name: str):
        """경매 물건 주소 → 단지 매칭 → 세대수.

        1순위: 단지 기본정보의 지번주소(kaptAddr)에 '동이름 지번' 이 포함
        2순위: 단지명 ↔ 건물명 유사 매칭
        반환: {"households": int|None, "kapt_name": str|None, "matched_by": str|None}
        """
        none = {"households": None, "kapt_name": None, "matched_by": None}
        if not self.enabled or not bjd_code:
            return none
        try:
            complexes = self._list_by_dong(bjd_code)
        except Exception:
            return none

        lot_main = (lotno or "").split("-")[0].strip()
        addr_probe = f"{dong_name} {lotno}".strip() if lotno else ""
        addr_probe_main = f"{dong_name} {lot_main}" if lot_main else ""

        # 1) 지번주소 매칭
        for c in complexes:
            code = c.get("kaptCode")
            if not code:
                continue
            try:
                basis = self._basis(code)
            except Exception:
                continue
            kapt_addr = basis.get("kaptAddr") or ""
            if addr_probe and addr_probe in kapt_addr:
                return {"households": basis["households"],
                        "kapt_name": basis["kaptName"], "matched_by": "지번주소"}
            if addr_probe_main and re.search(re.escape(addr_probe_main) + r"(?![0-9])", kapt_addr):
                return {"households": basis["households"],
                        "kapt_name": basis["kaptName"], "matched_by": "지번(본번)"}

        # 2) 단지명 매칭
        norm = lambda s: re.sub(r"[\s()\-·아파트]", "", s or "")
        target = norm(bld_name)
        if target:
            for c in complexes:
                if not c.get("kaptCode"):
                    continue
                cname = norm(c.get("kaptName"))
                if cname and (target in cname or cname in target):
                    basis = self._basis(c["kaptCode"])
                    return {"households": basis["households"],
                            "kapt_name": basis["kaptName"], "matched_by": "단지명"}
        return none


def _to_int(v):
    try:
        return int(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
