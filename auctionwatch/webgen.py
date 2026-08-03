"""정적 대시보드 생성 — 데이터(JSON)를 인라인으로 심은 단일 HTML 파일.

file:// 로 열어도 동작하도록 외부 요청 없이 자체 완결로 만든다.
카드마다: 종합 판별표 · 권리분석 · 자동 체크리스트 · 법률 분석 ·
입찰/명도 가이드 · 수익률 계산기(취득세 자동계산, 3개 시나리오, 역산 입찰가).
"""

import html
import json
from datetime import datetime
from pathlib import Path

TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  --bg:#f6f7f9; --card:#fff; --ink:#1c2430; --sub:#6b7684; --line:#e4e8ee;
  --safe:#1a936f; --warn:#e0a100; --danger:#d64545; --hold:#7a869a; --accent:#2456d6;
  --chip:#eef1f6;
}
@media (prefers-color-scheme: dark) {
  :root { --bg:#141821; --card:#1d2330; --ink:#e8ecf3; --sub:#93a0b4; --line:#2c3446; --chip:#252c3c; }
}
* { box-sizing:border-box; margin:0; }
body { font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard",sans-serif;
  background:var(--bg); color:var(--ink); padding:24px 16px 60px; }
.wrap { max-width:1080px; margin:0 auto; }
h1 { font-size:22px; margin-bottom:4px; }
.meta { color:var(--sub); font-size:13px; margin-bottom:20px; }
.stats { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:16px; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:10px 16px; font-size:13px; color:var(--sub); }
.stat b { display:block; font-size:20px; color:var(--ink); }
.tabs { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
.filters { background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:12px 16px; margin-bottom:16px; display:flex; gap:16px; align-items:flex-end; flex-wrap:wrap; }
.filters label { font-size:12px; color:var(--sub); display:flex; flex-direction:column; gap:4px; }
.filters input, .filters select { width:110px; padding:6px 8px; border:1px solid var(--line);
  border-radius:6px; background:var(--bg); color:var(--ink); font-size:13px; }
.filters .range { display:flex; gap:6px; align-items:center; }
.filters .range input { width:78px; }
.filters .btn { border:1px solid var(--line); background:var(--bg); color:var(--sub);
  border-radius:8px; padding:7px 12px; font-size:12px; cursor:pointer; }
.filters .hit { font-size:13px; color:var(--sub); margin-left:auto; align-self:center; }
.filters .hit b { color:var(--ink); font-size:16px; }
.chips { display:flex; gap:6px; flex-wrap:wrap; }
.chip { border:1px solid var(--line); background:var(--bg); color:var(--sub);
  border-radius:14px; padding:4px 11px; font-size:12px; cursor:pointer; }
.chip.on { background:var(--accent); border-color:var(--accent); color:#fff; }
.tab { border:1px solid var(--line); background:var(--card); color:var(--sub);
  border-radius:20px; padding:6px 14px; font-size:13px; cursor:pointer; }
.tab.on { background:var(--accent); border-color:var(--accent); color:#fff; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:16px 18px; margin-bottom:12px; }
.card summary { cursor:pointer; list-style:none; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
.card summary::-webkit-details-marker { display:none; }
.badge { font-size:12px; font-weight:700; padding:3px 10px; border-radius:12px; color:#fff; flex:none; }
.badge.safe { background:var(--safe); } .badge.warn { background:var(--warn); }
.badge.danger { background:var(--danger); } .badge.hold { background:var(--hold); }
.grade { font-size:13px; font-weight:800; padding:3px 9px; border-radius:8px; flex:none;
  background:var(--chip); color:var(--ink); border:1px solid var(--line); }
.grade.S { color:#fff; background:#7c3aed; border-color:#7c3aed; }
.grade.A { color:#fff; background:var(--safe); border-color:var(--safe); }
.grade.B { color:#fff; background:var(--accent); border-color:var(--accent); }
.grade.C { color:#fff; background:var(--warn); border-color:var(--warn); }
.grade.D { color:#fff; background:var(--danger); border-color:var(--danger); }
.addr { font-weight:600; font-size:15px; }
.sub { color:var(--sub); font-size:13px; }
.price { margin-left:auto; text-align:right; font-size:13px; color:var(--sub); }
.price b { color:var(--ink); font-size:15px; }
.body { margin-top:14px; border-top:1px solid var(--line); padding-top:14px; font-size:14px; line-height:1.65; }
.body h4 { font-size:13px; color:var(--sub); margin:14px 0 5px; }
.flags { display:flex; gap:6px; flex-wrap:wrap; margin:6px 0; }
.flag { font-size:12px; background:rgba(214,69,69,.12); color:var(--danger);
  border-radius:6px; padding:2px 8px; }
ul { padding-left:20px; }
table.tbl { border-collapse:collapse; width:100%; font-size:13px; margin:4px 0; }
table.tbl th, table.tbl td { border:1px solid var(--line); padding:6px 9px; text-align:left; }
table.tbl th { background:var(--chip); color:var(--sub); font-weight:600; white-space:nowrap; }
table.tbl td.num { text-align:right; font-variant-numeric:tabular-nums; }
.chk { list-style:none; padding:0; }
.chk li { padding:3px 0; font-size:13px; }
.chk .ok::before { content:"✓ "; color:var(--safe); font-weight:700; }
.chk .warn::before { content:"⚠ "; color:var(--warn); font-weight:700; }
.chk .danger::before { content:"✕ "; color:var(--danger); font-weight:700; }
.calc { background:var(--chip); border-radius:10px; padding:12px 14px; margin-top:6px; }
.calc .row { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:8px; }
.calc label { font-size:12px; color:var(--sub); display:flex; flex-direction:column; gap:3px; }
.calc input, .calc select { width:120px; padding:5px 7px; border:1px solid var(--line);
  border-radius:6px; background:var(--card); color:var(--ink); font-size:13px; }
.calc .note { font-size:11px; color:var(--sub); margin-top:8px; line-height:1.5; }
.loc { display:flex; gap:14px; flex-wrap:wrap; font-size:13px; }
.loc b { font-size:16px; }
.maplinks { display:flex; gap:8px; flex-wrap:wrap; margin:4px 0 2px; }
.maplinks a { border:1px solid var(--line); background:var(--chip); color:var(--ink);
  border-radius:8px; padding:6px 12px; font-size:12px; text-decoration:none; }
.maplinks a:hover { border-color:var(--accent); color:var(--accent); }
.guide { background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:4px 18px 14px; margin-bottom:16px; }
.guide summary { cursor:pointer; list-style:none; padding:12px 0; font-weight:600; font-size:14px; }
.guide summary::-webkit-details-marker { display:none; }
.guide h5 { font-size:13px; margin:14px 0 5px; color:var(--accent); }
.guide ol, .guide ul { padding-left:20px; font-size:13px; line-height:1.75; }
.guide .warn-box { background:rgba(224,161,0,.1); border-left:3px solid var(--warn);
  padding:9px 12px; border-radius:6px; font-size:12.5px; line-height:1.6; margin:10px 0; }
/* 용어 툴팁 */
.gl { font-style:normal; border-bottom:1px dashed var(--accent); cursor:help; }
.gl:hover { background:rgba(36,86,214,.09); }
#glpop { position:absolute; z-index:99; max-width:330px; display:none;
  background:var(--card); border:1px solid var(--accent); border-radius:10px;
  padding:11px 14px; font-size:13px; line-height:1.6; color:var(--ink);
  box-shadow:0 6px 24px rgba(0,0,0,.22); }
#glpop b { color:var(--accent); }
.glossary { columns:2; column-gap:22px; font-size:13px; line-height:1.6; }
.glossary dt { font-weight:700; margin-top:9px; color:var(--accent); break-after:avoid; }
.glossary dd { margin:2px 0 0; color:var(--sub); }
@media (max-width:640px) { .glossary { columns:1; } }
.disclaimer { margin-top:28px; color:var(--sub); font-size:12px; line-height:1.6;
  border-top:1px solid var(--line); padding-top:14px; }
.empty { text-align:center; color:var(--sub); padding:60px 0; }
a { color:var(--accent); }
</style>
</head>
<body>
<div class="wrap">
<h1>__TITLE__</h1>
<div class="meta">갱신: __UPDATED__ · 조건: 아파트 · __MIN_HH__세대 이상__AREA__ · 유찰 __MAX_FB__회 이하 · 매각기일 __WINDOW__일 이내__REGIONS__</div>
<div class="stats" id="stats"></div>

<details class="guide">
<summary>📋 경매 참석 절차 — 처음이라면 이것부터 (펼치기)</summary>

<h5>1단계 · 입찰 전 준비 (기일 1~2주 전)</h5>
<ol>
  <li><b>등기부등본 발급</b> — <a href="https://www.iros.go.kr" target="_blank" rel="noopener">인터넷등기소</a>에서 열람 700원. 대시보드 분석은 등기부 없이 한 1차 스크리닝이므로, 말소기준권리 이전에 설정된 권리가 실제로 없는지 여기서 확정한다.</li>
  <li><b>전입세대열람</b> — 주민센터에서 경매 물건 주소로 신청(경매 참가자는 매각공고문 지참 시 열람 가능). 현황조사서 이후 새로 전입한 세대가 있는지 본다.</li>
  <li><b>매각물건명세서·현황조사서·감정평가서 열람</b> — 기일 1주 전부터 법원 민사집행과 또는 <a href="https://www.courtauction.go.kr" target="_blank" rel="noopener">법원경매정보</a>에서 확인. 특히 <b>비고란</b>은 원문을 직접 읽는다.</li>
  <li><b>현장 확인(임장)</b> — 실제 점유자, 관리비 체납액(관리사무소), 누수·파손, 주차, 일조. 관리비 체납 중 공용부분은 낙찰자가 인수한다.</li>
  <li><b>자금 계획</b> — 대금은 낙찰 후 약 <b>1개월 내 완납</b>이 원칙이다. 경락잔금대출 한도를 미리 확인해 둔다.</li>
</ol>

<h5>2단계 · 입찰 당일 (매각기일)</h5>
<ul>
  <li><b>준비물</b> — 신분증, 도장(막도장 가능), <b>입찰보증금</b>(최저매각가격의 10%, 특별매각조건이면 20%·30%). <b>보증금은 수표 한 장</b>으로 준비하는 것이 안전하다(현금은 계수 시간이 걸린다).</li>
  <li><b>시간</b> — 보통 오전 10시 개시, 입찰 마감은 <b>10시 10~20분경</b>. 마감되면 예외 없이 참여 불가하므로 30분 이상 여유를 두고 도착한다.</li>
  <li><b>기일입찰표 작성</b> — 사건번호·물건번호·입찰가격·보증금액. <b>입찰가격은 고쳐 쓸 수 없다</b>(수정하면 무효, 새 용지를 받는다). 물건번호가 여러 개인 사건은 물건번호를 반드시 적는다.</li>
  <li><b>흔한 무효 사유</b> — 최저매각가격 미만 기재, 보증금 부족, 입찰가격 정정, 물건번호 누락, <b>0 하나를 더 쓰는 실수</b>(가장 치명적).</li>
  <li><b>개찰</b> — 최고가매수신고인이 결정되고, 차순위매수신고를 받는다. 패찰자는 보증금을 즉시 반환받는다.</li>
  <li><b>대리 입찰</b> — 위임장 + 인감증명서 필요. 업(業)으로 하는 대리는 매수신청대리 등록(공인중개사·변호사)이 필요하다.</li>
</ul>

<h5>3단계 · 낙찰 후</h5>
<ol>
  <li><b>매각허가결정</b> — 기일로부터 약 1주. 이후 1주간 항고 기간.</li>
  <li><b>대금 납부</b> — 허가 확정 후 통상 1개월 내 지정된 기한까지 완납. <b>미납하면 보증금을 몰수</b>당하고 재매각된다.</li>
  <li><b>소유권이전등기·취득세</b> — 취득세는 취득일부터 <b>60일 내</b> 신고·납부(카드별 세부 조건은 지자체 확인).</li>
  <li><b>인도명령 신청</b> — 대금 완납 후 <b>6개월 내</b> 신청. 대항력 없는 점유자에게 쓰는 가장 강력한 수단이다.</li>
  <li><b>배당기일</b> — 임차인이 배당을 받으려면 매수인의 <b>인도확인서</b>가 필요한 경우가 많아, 명도 협상의 지렛대가 된다.</li>
</ol>

<div class="warn-box">
<b>초보자가 가장 많이 다치는 지점</b> — ① 대항력 있는 임차인의 보증금을 인수하게 되는 경우,
② 지분·전세권 매각 물건을 전체 소유권으로 오해하는 경우, ③ 유치권 신고 물건에서 명도가
장기화되는 경우, ④ 시세를 확인하지 않고 감정가를 시세로 믿는 경우.
카드의 <b>자동 권리 체크리스트</b>와 <b>종합 등급</b>이 이 네 가지를 먼저 걸러주도록 만들어져 있다.
</div>
</details>

<details class="guide">
<summary>📖 경매 용어 사전 — 모르는 말이 나오면 여기 (펼치기)</summary>
<div class="warn-box">본문에 <i class="gl" data-t="말소기준권리">점선 밑줄</i>이 있는 낱말은 <b>눌러보면</b> 설명이 나옵니다.</div>
<dl class="glossary" id="glossary-list"></dl>
</details>

<div class="tabs" id="tabs"></div>
<div class="filters">
  <label>최저매각가 (억)
    <span class="range">
      <input id="f-pmin" type="number" step="0.5" placeholder="하한" oninput="render()">
      <span class="sub">~</span>
      <input id="f-pmax" type="number" step="0.5" placeholder="상한" oninput="render()">
    </span>
  </label>
  <label>빠른 선택
    <span class="chips" id="f-presets"></span>
  </label>
  <label>전용면적 (㎡)
    <span class="range">
      <input id="f-amin" type="number" step="1" placeholder="하한" oninput="render()">
      <span class="sub">~</span>
      <input id="f-amax" type="number" step="1" placeholder="상한" oninput="render()">
    </span>
  </label>
  <label>최소 세대수
    <input id="f-hh" type="number" step="100" placeholder="예: 500" oninput="render()">
  </label>
  <label>등급
    <select id="f-grade" onchange="render()">
      <option value="">전체</option>
      <option value="S">S만</option>
      <option value="SA">S~A</option>
      <option value="SAB">S~B</option>
    </select>
  </label>
  <label>정렬
    <select id="f-sort" onchange="render()">
      <option value="grade">종합등급</option>
      <option value="price-asc">최저가 낮은순</option>
      <option value="price-desc">최저가 높은순</option>
      <option value="rate">감정가 대비 저렴한순</option>
      <option value="date">매각기일 임박순</option>
      <option value="hh">세대수 많은순</option>
    </select>
  </label>
  <button class="btn" onclick="resetFilters()">초기화</button>
  <span class="hit" id="f-hit"></span>
</div>
<div id="list"></div>
<div id="glpop"></div>
<div class="disclaimer">
⚠️ 본 페이지의 권리분석·입지평가·법률메모는 법원경매정보 공개 자료만을 근거로 AI가 수행한
1차 스크리닝이며, 시세 참고치는 네이버 매물 호가(전체 평형 혼합)입니다. 수익률 계산기는
단순화된 세율·비용 가정을 사용합니다(계산기 하단 가정 참조). 등기부등본·건축물대장·현장 확인과
세무사·법무사 자문을 대체하지 않으며, 투자 판단 및 법률·세무 자문이 아닙니다.
</div>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);

// ── 용어 사전 ─────────────────────────────────────────────────
// 본문에 나오는 경매 용어에 자동으로 설명 툴팁을 붙인다.
// 겹치는 용어(근저당권 ⊂ 말소기준권리 문맥)는 긴 것부터 치환해 충돌을 막는다.
const GLOSSARY = {
  "말소기준권리": "낙찰되면 이 권리와 그보다 나중에 생긴 권리들이 모두 지워집니다. 반대로 이보다 먼저 생긴 권리는 낙찰자가 그대로 떠안습니다. 경매 권리분석의 기준선입니다.",
  "최선순위 설정": "말소기준권리와 같은 뜻입니다. 등기부에서 가장 먼저 잡힌 담보권 등의 설정일을 말합니다.",
  "대항력": "임차인이 '나는 계속 살 권리가 있다'고 새 집주인(낙찰자)에게 주장할 수 있는 힘입니다. 전입신고를 말소기준권리보다 먼저 했으면 생깁니다.",
  "우선변제권": "임차인이 낙찰대금에서 다른 채권자보다 먼저 보증금을 받아갈 권리입니다. 전입신고 + 확정일자가 있어야 생깁니다.",
  "확정일자": "임대차계약서에 주민센터가 찍어주는 날짜 도장입니다. 이 날짜가 배당 순서를 정합니다.",
  "배당요구종기": "임차인·채권자가 '나도 돈 받아야 한다'고 신청할 수 있는 마감일입니다. 이 날까지 신청하지 않은 임차인의 보증금은 낙찰자가 물어줘야 할 수 있습니다.",
  "배당요구": "낙찰대금에서 돈을 받겠다고 법원에 신청하는 것입니다.",
  "인수": "낙찰자가 떠안는다는 뜻입니다. 낙찰가 외에 추가로 돈을 더 내야 한다는 의미입니다.",
  "최저매각가격": "그 날 입찰에서 쓸 수 있는 최소 금액입니다. 이보다 적게 쓰면 무효입니다.",
  "감정평가액": "법원이 감정평가사에게 맡겨 매긴 값입니다. 시세와 다를 수 있어 실거래가 확인이 필요합니다.",
  "유찰": "입찰자가 없어 그 날 매각이 안 된 것입니다. 다음 기일에는 가격이 20~30% 떨어집니다.",
  "입찰보증금": "입찰할 때 미리 내는 돈으로 보통 최저매각가격의 10%입니다. 떨어지면 그 자리에서 돌려받습니다.",
  "매각물건명세서": "법원이 만든 물건 설명서입니다. 낙찰자가 떠안을 권리가 여기에 적힙니다. 가장 중요한 서류입니다.",
  "현황조사서": "집행관이 직접 가서 누가 살고 있는지 조사한 기록입니다.",
  "임차권등기": "보증금을 못 받은 세입자가 등기부에 '내 보증금 아직 못 받았다'고 표시해 둔 것입니다. 이사를 가도 권리가 유지됩니다.",
  "전세권": "전세금을 낸 사람이 등기부에 정식으로 올린 권리입니다. 등기 없는 일반 전세와 다릅니다.",
  "유치권": "공사비 등을 못 받은 사람이 '돈 받을 때까지 안 나간다'며 건물을 붙잡고 있는 권리입니다. 등기부에 안 나타나서 가장 위험합니다.",
  "근저당권": "은행 등이 돈을 빌려주고 집을 담보로 잡은 것입니다. 경매의 가장 흔한 원인입니다.",
  "가압류": "재판 결과가 나오기 전에 재산을 함부로 팔지 못하게 임시로 묶어두는 것입니다.",
  "압류": "세금이나 빚 때문에 재산을 강제로 묶어두는 것입니다.",
  "지분매각": "집 전체가 아니라 여러 명이 나눠 가진 지분 일부만 파는 것입니다. 낙찰해도 혼자서는 팔거나 쓸 수 없어 초보자는 피해야 합니다.",
  "우선매수": "공동소유자가 '내가 같은 값에 사겠다'고 먼저 살 수 있는 권리입니다. 이게 행사되면 낙찰이 취소됩니다.",
  "인도명령": "낙찰자가 대금을 다 낸 뒤 법원에 '점유자를 내보내 달라'고 신청하는 제도입니다. 소송보다 훨씬 빠릅니다.",
  "명도": "집에 살고 있는 사람을 내보내고 집을 넘겨받는 과정입니다.",
  "무잉여": "낙찰대금으로 경매 신청한 채권자에게 돌아갈 돈이 없는 상황입니다. 이 경우 경매가 취소됩니다.",
  "특별매각조건": "보증금을 10%가 아니라 20~30%로 올리는 등 그 물건에만 붙은 조건입니다. 보통 앞서 낙찰자가 대금을 안 낸 물건입니다.",
  "재매각": "먼저 낙찰된 사람이 대금을 내지 않아 다시 경매에 나온 것입니다.",
  "기일입찰": "정해진 날에 법정에 직접 가서 입찰하는 방식입니다. 대부분의 아파트 경매가 이 방식입니다.",
  "차순위매수신고": "1등 다음으로 높게 쓴 사람이 '1등이 대금 안 내면 내가 사겠다'고 신고하는 것입니다.",
  "대지권": "아파트에 딸린 땅에 대한 권리입니다. 이게 등기되지 않았으면 나중에 문제가 될 수 있습니다.",
  "별도등기": "건물과 땅의 등기가 따로 되어 있는 상태입니다. 땅에 걸린 권리를 떠안을 수 있습니다.",
  "임의경매": "은행 등이 담보(근저당)를 근거로 신청한 경매입니다.",
  "강제경매": "판결문 등을 근거로 신청한 경매입니다. 담보가 없어 권리관계가 더 복잡할 수 있습니다.",
  "매각허가결정": "법원이 '이 낙찰을 인정한다'고 확정하는 것입니다. 보통 낙찰 1주 뒤입니다.",
  "취하": "경매를 신청한 채권자가 빚을 받아 신청을 거둬들이는 것입니다. 경매가 없어집니다.",
  "전입세대열람": "그 집에 주민등록을 한 세대가 있는지 주민센터에서 확인하는 것입니다. 숨은 임차인을 찾는 방법입니다.",
  "등기부등본": "부동산의 권리관계가 전부 적힌 공식 문서입니다. 입찰 전 반드시 발급해 확인해야 합니다.",
  "말소": "등기부에서 지워지는 것입니다.",
  "조합원 지위 승계": "재건축 아파트를 사면 조합원 자격도 따라오는지를 말합니다. 투기과열지구에서 조합설립인가 뒤에 산 사람은 원칙적으로 조합원이 못 되고 현금으로 정산받고 나가야 합니다(현금청산). 경매는 예외가 인정될 수 있지만 조건이 있습니다.",
  "현금청산": "조합원이 되지 못해 아파트를 못 받고 감정가만 돈으로 받고 나가는 것입니다. 재건축 기대로 비싸게 낙찰했다면 큰 손해입니다.",
  "투기과열지구": "집값이 급등한 지역을 정부가 지정해 규제를 강하게 적용하는 곳입니다. 여기서만 조합원 지위 승계 제한이 걸립니다.",
  "조합설립인가": "재건축 조합이 정식으로 설립 허가를 받은 것입니다. 이 시점 이후 매수하면 조합원 승계 제한이 생길 수 있습니다.",
  "재건축 연한": "준공 후 30년이 지나면 재건축을 추진할 수 있습니다. 연한이 지났다고 바로 되는 건 아니고 안전진단 등 절차가 남습니다.",
  "1기 신도시": "분당·일산·평촌·산본·중동입니다. 노후계획도시 특별법으로 재건축을 함께 추진하는 지역이라 기대가 가격에 반영돼 있습니다.",
  "선도지구": "1기 신도시에서 재건축을 먼저 추진하도록 선정된 단지입니다.",
  "인도확인서": "낙찰자가 '집을 넘겨받았다'고 확인해 주는 서류입니다. 임차인이 배당금을 받으려면 이게 필요해서 명도 협상의 카드가 됩니다.",
};
const GL_TERMS = Object.keys(GLOSSARY).sort((a,b) => b.length - a.length);
const GL_RE = new RegExp("(" + GL_TERMS.map(t => t.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&")).join("|") + ")", "g");

// esc() 로 이스케이프된 텍스트에 용어 툴팁을 입힌다. 이미 태그 안에 있는
// 구간은 건드리지 않도록 태그 단위로 쪼개서 처리한다.
function gl(escaped){
  if (!escaped) return escaped;
  return String(escaped).split(/(<[^>]*>)/).map(seg =>
    seg.startsWith("<") ? seg
      : seg.replace(GL_RE, m => `<i class="gl" data-t="${m}">${m}</i>`)
  ).join("");
}
function showGl(el){
  const t = el.getAttribute("data-t");
  const box = document.getElementById("glpop");
  box.innerHTML = `<b>${t}</b><br>${GLOSSARY[t] || ""}`;
  const r = el.getBoundingClientRect();
  box.style.display = "block";
  const top = r.bottom + window.scrollY + 6;
  const left = Math.min(r.left + window.scrollX, window.innerWidth - box.offsetWidth - 16);
  box.style.top = top + "px"; box.style.left = Math.max(8, left) + "px";
}
document.addEventListener("click", e => {
  const t = e.target.closest(".gl");
  if (t) { showGl(t); e.stopPropagation(); }
  else document.getElementById("glpop").style.display = "none";
});
const V = { "안전":["safe","안전"], "주의":["warn","주의"], "위험":["danger","위험"] };
const GRADE_MEAN = {
  "S": "최우선 검토 — 권리도 깨끗하고 가격도 좋습니다",
  "A": "괜찮은 물건 — 떠안을 권리가 없습니다",
  "B": "조건부 — 한두 가지를 확인하면 괜찮습니다",
  "C": "확인 필수 — 확인 안 하면 손해 볼 수 있습니다",
  "D": "초보자 접근 금지 — 구조 자체가 어렵습니다",
};
const VERDICT_MEAN = {
  "안전": "(낙찰가 외에 더 물어줄 돈이 없어 보입니다)",
  "주의": "(더 물어줄 돈이 생길 수 있어 확인이 필요합니다)",
  "위험": "(그대로 입찰하면 손해를 볼 수 있습니다)",
};
const fmt = n => n==null ? "-" : Number(n).toLocaleString("ko-KR");
const fmtEok = n => n==null ? "-" : (n/1e8).toFixed(2).replace(/\\.?0+$/,"") + "억";
const d8 = s => s && s.length===8 ? `${s.slice(0,4)}.${s.slice(4,6)}.${s.slice(6)}` : (s||"-");

function badge(it){
  if (it.status === "analyzed") { const [cls,label] = V[it.analysis.verdict] || ["hold", it.analysis.verdict]; return [cls,label]; }
  if (it.status === "households_unknown") return ["hold","세대수 미확인"];
  if (it.status === "pending") return ["hold","분석 대기"];
  if (it.status === "error") return ["hold","분석 실패"];
  return ["hold", it.status];
}

const TABS = [["all","전체"],["안전","안전"],["주의","주의"],["위험","위험"],["hold","보류/대기"]];
let cur = "all";
function verdictMatch(it){
  if (cur === "all") return true;
  if (cur === "hold") return it.status !== "analyzed";
  return it.status === "analyzed" && it.analysis.verdict === cur;
}

// ── 웹 필터 ───────────────────────────────────────────────────
const PRESETS = [["~5억",null,5],["5~10억",5,10],["10~15억",10,15],["15~20억",15,20],["20억~",20,null]];
const num = id => { const v = parseFloat((document.getElementById(id)||{}).value); return isNaN(v) ? null : v; };
function filterState(){
  return {pmin:num('f-pmin'), pmax:num('f-pmax'), amin:num('f-amin'), amax:num('f-amax'),
          hh:num('f-hh'), grade:document.getElementById('f-grade').value,
          sort:document.getElementById('f-sort').value};
}
function applyPreset(i){
  const [, lo, hi] = PRESETS[i];
  const pm = document.getElementById('f-pmin'), px = document.getElementById('f-pmax');
  const active = (pm.value === (lo===null?"":String(lo))) && (px.value === (hi===null?"":String(hi)));
  pm.value = active ? "" : (lo===null ? "" : lo);
  px.value = active ? "" : (hi===null ? "" : hi);
  render();
}
function resetFilters(){
  ['f-pmin','f-pmax','f-amin','f-amax','f-hh'].forEach(id => document.getElementById(id).value = "");
  document.getElementById('f-grade').value = "";
  document.getElementById('f-sort').value = "grade";
  cur = "all";
  render();
}
function match(it){
  if (!verdictMatch(it)) return false;
  const f = filterState();
  const p = (it.min_price||0)/1e8, a = it.area_m2||0, h = it.households||0;
  if (f.pmin !== null && p < f.pmin) return false;
  if (f.pmax !== null && p > f.pmax) return false;
  if (f.amin !== null && a && a < f.amin) return false;
  if (f.amax !== null && a && a > f.amax) return false;
  if (f.hh !== null && h < f.hh) return false;
  if (f.grade) {
    const g = (it.analysis && it.analysis.overall) ? it.analysis.overall.grade : null;
    if (!g || !f.grade.includes(g)) return false;
  }
  return true;
}
const GRADE_ORD = {S:0, A:1, B:2, C:3, D:4};
function sortItems(items, mode){
  const g = it => GRADE_ORD[(it.analysis && it.analysis.overall) ? it.analysis.overall.grade : ""] ?? 9;
  const rate = it => it.appraisal ? it.min_price/it.appraisal : 9;
  const cmp = {
    "grade":      (x,y) => g(x)-g(y) || (y.analysis?.score||0)-(x.analysis?.score||0),
    "price-asc":  (x,y) => (x.min_price||0)-(y.min_price||0),
    "price-desc": (x,y) => (y.min_price||0)-(x.min_price||0),
    "rate":       (x,y) => rate(x)-rate(y),
    "date":       (x,y) => String(x.bid_date||"").localeCompare(String(y.bid_date||"")),
    "hh":         (x,y) => (y.households||0)-(x.households||0),
  }[mode] || ((x,y)=>0);
  return items.slice().sort((x,y) => cmp(x,y) || String(x.bid_date||"").localeCompare(String(y.bid_date||"")));
}

// ── 세금 자동계산 ─────────────────────────────────────────────
function acqTaxDetail(price, over85, multi){
  const base = multi ? 8.0 : (price <= 6e8 ? 1.0 : price >= 9e8 ? 3.0 : (price/1e8*(2/3) - 3));
  const edu = multi ? 0.4 : base/10;          // 지방교육세
  const rural = over85 ? 0.2 : 0;             // 농어촌특별세 (85㎡ 초과)
  return {
    baseRate: base, eduRate: edu, ruralRate: rural,
    base: price*base/100, edu: price*edu/100, rural: price*rural/100,
    total: price*(base+edu+rural)/100,
  };
}
function acqTax(price, over85, multi){ return acqTaxDetail(price, over85, multi).total; }
function cgTaxDetail(gain, months){
  // 양도소득세 근사 — 지방소득세 10% 포함, 기본공제·장특공제 미반영
  const rate = months < 12 ? 0.77 : months < 24 ? 0.66 : 0.44;
  const label = months < 12 ? "1년 미만 (70%+지방세)" : months < 24 ? "2년 미만 (60%+지방세)" : "2년 이상 (기본세율 근사 40%+지방세)";
  return {rate, label, tax: gain > 0 ? gain*rate : 0};
}

// ── 지도 연동 ─────────────────────────────────────────────────
// 좌표 API 키가 필요 없는 외부 링크 방식.
//
// 지도 앱은 지번 주소보다 '동이름 + 단지명' 으로 훨씬 정확하게 찾는다
// (특히 구글맵은 한국 지번 검색 정확도가 낮다). 그래서 단지명이 확인된
// 물건은 단지명을 검색어로, 확인되지 않은 물건만 지번 주소를 쓴다.
function addrParts(it){
  const raw = String(it.addr||"");
  const plain = raw.split("(")[0].trim();
  // 지번/도로명까지만 남기고 동·층·호 제거
  let base = plain;
  const m = plain.match(/^(.*?[ ][0-9]+(?:-[0-9]+)?)[ ]/);
  if (m) base = m[1];
  else base = plain.replace(/[ ](제?[0-9]+동|[0-9]+층|[0-9]+호).*$/, "").trim();
  // '서울특별시 중구 신당동 842' → 시군구 + 동
  const tok = base.split(/\s+/);
  const region = tok.slice(0, Math.max(2, tok.length - 1)).join(" ");
  return {base, region};
}
function mapQuery(it){
  const {base, region} = addrParts(it);
  // 단지명이 확인된 물건은 '지역 + 단지명', 아니면 지번 주소
  if (it.kapt_name) {
    const dong = region.split(/\s+/).slice(-1)[0] || "";
    return `${dong} ${it.kapt_name}`.trim();
  }
  return base;
}
function mapLinks(it){
  const query = mapQuery(it);
  const q = encodeURIComponent(query);
  const addrQ = encodeURIComponent(addrParts(it).base);
  const links = [
    [`https://map.naver.com/p/search/${q}`, "🗺 네이버지도", "단지 위치·로드뷰"],
    [`https://map.kakao.com/?q=${q}`, "🗺 카카오맵", "단지 위치·로드뷰"],
    [`https://www.google.com/maps/search/?api=1&query=${q}`, "🌐 구글맵", "위성사진"],
  ];
  // 네이버 단지정보는 단지 ID가 확인된 경우에만 (엉뚱한 검색 결과로 보내지 않기 위해)
  if (it.market && it.market.complex_no)
    links.push([`https://fin.land.naver.com/complexes/${it.market.complex_no}`,
                "🏢 네이버 부동산", "시세·매물·평형별 정보"]);
  links.push([`https://www.google.com/search?q=${encodeURIComponent(query + " 실거래가")}`,
              "📊 실거래가 검색", "국토부·포털 실거래가"]);
  const note = it.kapt_name
    ? `검색어: <b>${esc(query)}</b>`
    : `단지명이 확인되지 않아 지번 주소로 검색합니다: <b>${esc(query)}</b>`;
  return {html: links.map(([u,l,t]) =>
    `<a href="${u}" target="_blank" rel="noopener" title="${esc(t)}">${l}</a>`).join(""), note};
}

// 기본 예상 매도가 — 단지 호가 밴드 중간값(전 평형 혼합)이 있으면 그것, 없으면 감정가.
// 어느 쪽이든 평형별 시세가 아니므로 사용자가 반드시 수정해야 하는 출발점.
function defaultSell(it){
  const mk = it.market || {};
  if (mk.asking_min && mk.asking_max) return (mk.asking_min + mk.asking_max) / 2;
  return it.appraisal || it.min_price || 0;
}

// ── 수익률 계산기 ─────────────────────────────────────────────
function calcProfit(p){
  // p: {bid, sell, ltv, rate, months, repair, evict, over85, multi}
  const tax = acqTax(p.bid, p.over85, p.multi);
  const legal = Math.max(p.bid*0.001, 500000);
  const loan = p.bid * p.ltv;
  const interest = loan * p.rate * (p.months/12);
  const brokerage = p.sell * 0.005;
  const holdTax = p.bid * 0.002 * (p.months/12);   // 재산세 등 보유비용 근사
  const costs = tax + legal + p.repair + p.evict + interest + brokerage + holdTax;
  const gross = p.sell - p.bid - costs;
  const cg = cgTaxDetail(gross, p.months);
  const net = gross - cg.tax;
  const equity = p.bid - loan + tax + legal + p.repair + p.evict;
  return {tax, legal, interest, brokerage, holdTax, costs, gross,
          cgTax: cg.tax, cg, net, equity,
          roe: equity > 0 ? net/equity*100 : 0};
}
function scenarios(p){
  return [
    ["보수", {...p, sell: p.sell*0.93, repair: p.repair*1.5, months: p.months+6}],
    ["기준", {...p}],
    ["공격", {...p, sell: p.sell*1.07}],
  ].map(([name, q]) => ({name, sell: q.sell, r: calcProfit(q)}));
}
function reverseBid(p, targetRoe){
  let lo = p.sell*0.2, hi = p.sell*1.2;
  for (let i=0;i<60;i++){
    const mid = (lo+hi)/2;
    const r = calcProfit({...p, bid: mid});
    if (r.roe >= targetRoe) lo = mid; else hi = mid;
  }
  return lo;
}
function readCalc(id, it){
  const g = k => { const el = document.getElementById(`c-${k}-${id}`); return el ? parseFloat(el.value) : NaN; };
  return {
    bid: (g('bid')||0)*1e4, sell: (g('sell')||0)*1e4,
    ltv: (g('ltv')||0)/100, rate: (g('rate')||0)/100,
    months: g('months')||12, repair: (g('repair')||0)*1e4, evict: (g('evict')||0)*1e4,
    over85: it.area_m2 ? it.area_m2 > 85 : false,
    multi: document.getElementById(`c-multi-${id}`).value === "1",
  };
}
function runCalc(id){
  const it = DATA.items.find(x => x.key === id);
  const p = readCalc(id, it);
  const scn = scenarios(p);
  const rows = scn.map(s => `<tr><th>${s.name}</th><td class="num">${fmtEok(s.sell)}</td>
    <td class="num">${fmtEok(s.r.costs + s.r.cgTax)}</td><td class="num" style="color:${s.r.net>=0?'var(--safe)':'var(--danger)'};font-weight:700">${fmtEok(s.r.net)}</td>
    <td class="num" style="color:${s.r.roe>=0?'var(--ink)':'var(--danger)'}">${s.r.roe.toFixed(1)}%</td></tr>`).join("");
  const base = calcProfit(p);
  const at = acqTaxDetail(p.bid, p.over85, p.multi);
  document.getElementById(`calc-out-${id}`).innerHTML = `
    <h4 style="margin-top:10px">세금 자동계산</h4>
    <table class="tbl">
      <tr><th>세목</th><th>세율</th><th class="num">세액</th><th>비고</th></tr>
      <tr><th>취득세</th><td>${at.baseRate.toFixed(2)}%</td><td class="num">${fmt(Math.round(at.base))}원</td><td>${p.multi ? "다주택 중과" : "표준세율"}</td></tr>
      <tr><th>지방교육세</th><td>${at.eduRate.toFixed(2)}%</td><td class="num">${fmt(Math.round(at.edu))}원</td><td>취득세의 10%</td></tr>
      <tr><th>농어촌특별세</th><td>${at.ruralRate.toFixed(2)}%</td><td class="num">${fmt(Math.round(at.rural))}원</td><td>${p.over85 ? "전용 85㎡ 초과" : "85㎡ 이하 비과세"}</td></tr>
      <tr><th>취득 단계 합계</th><td>${(at.baseRate+at.eduRate+at.ruralRate).toFixed(2)}%</td><td class="num"><b>${fmt(Math.round(at.total))}원</b></td><td>낙찰 후 60일 내 신고·납부</td></tr>
      <tr><th>보유세(근사)</th><td>연 0.2%</td><td class="num">${fmt(Math.round(base.holdTax))}원</td><td>보유 ${p.months}개월분 재산세·종부세 근사</td></tr>
      <tr><th>양도소득세(근사)</th><td>${(base.cg.rate*100).toFixed(0)}%</td><td class="num">${fmt(Math.round(base.cgTax))}원</td><td>${esc(base.cg.label)}</td></tr>
    </table>
    <h4 style="margin-top:12px">시나리오 3개 비교</h4>
    <div class="sub" style="margin:4px 0">대출이자(기간 합) <b>${fmtEok(base.interest)}</b> ·
      매도 중개수수료 <b>${fmtEok(base.brokerage)}</b> · 투입 자기자본 <b>${fmtEok(base.equity)}</b></div>
    <table class="tbl"><tr><th>시나리오</th><th class="num">매도가</th><th class="num">총비용+세금</th><th class="num">세후이익</th><th class="num">자기자본수익률</th></tr>${rows}</table>
    <div class="sub" style="margin-top:4px">보수 = 매도가 -7%·수리비 1.5배·보유 +6개월 / 공격 = 매도가 +7%</div>`;
  const tgt = parseFloat(document.getElementById(`c-target-${id}`).value)||15;
  const rb = reverseBid(p, tgt);
  const minP = it.min_price || 0;
  const verdict = rb >= minP
    ? `<span style="color:var(--safe)">최저매각가(${fmtEok(minP)}) 위 — 이번 기일 응찰로 목표 달성 가능</span>`
    : `<span style="color:var(--danger)">최저매각가(${fmtEok(minP)}) 아래 — 이번 기일에는 목표 수익률 불가, 유찰 대기 필요</span>`;
  document.getElementById(`rev-h-${id}`).style.display = "";
  document.getElementById(`rev-out-${id}`).innerHTML =
    `목표 자기자본수익률 <b>${tgt}%</b> 달성 상한선: <b style="color:var(--accent);font-size:16px">${fmtEok(rb)}</b>
     (${fmt(Math.round(rb))}원) 이하로 응찰해야 합니다.<br>${verdict}`;
}

function render(){
  const tabs = document.getElementById('tabs');
  tabs.innerHTML = TABS.map(([k,l]) => {
    const n = DATA.items.filter(it => { const p = cur; cur = k; const m = match(it); cur = p; return m; }).length;
    return `<button class="tab ${cur===k?'on':''}" onclick="cur='${k}';render()">${l} (${n})</button>`;
  }).join("");

  const pm = document.getElementById('f-pmin').value, px = document.getElementById('f-pmax').value;
  document.getElementById('f-presets').innerHTML = PRESETS.map(([lbl,lo,hi],i) => {
    const on = pm === (lo===null?"":String(lo)) && px === (hi===null?"":String(hi)) && (pm||px);
    return `<button class="chip ${on?'on':''}" onclick="applyPreset(${i})">${lbl}</button>`;
  }).join("");

  const counts = { analyzed:0, safe:0, hold:0 };
  DATA.items.forEach(it => {
    if (it.status === "analyzed") { counts.analyzed++; if (it.analysis.verdict === "안전") counts.safe++; }
    else counts.hold++;
  });
  document.getElementById('stats').innerHTML = `
    <div class="stat">표시 물건<b>${DATA.items.length}</b></div>
    <div class="stat">분석 완료<b>${counts.analyzed}</b></div>
    <div class="stat">권리 이슈 없음<b style="color:var(--safe)">${counts.safe}</b></div>
    <div class="stat">보류/대기<b>${counts.hold}</b></div>`;

  const list = document.getElementById('list');
  const items = sortItems(DATA.items.filter(match), filterState().sort);
  document.getElementById('f-hit').innerHTML = `조건 충족 <b>${items.length}</b> / ${DATA.items.length}건`;
  if (!items.length) {
    list.innerHTML = `<div class="empty">조건에 맞는 물건이 없습니다. <button class="btn" onclick="resetFilters()">필터 초기화</button></div>`;
    return;
  }
  list.innerHTML = items.map(card).join("");
}

function card(it){
  const [cls,label] = badge(it);
  const a = it.analysis;
  const rate = it.appraisal ? Math.round(it.min_price / it.appraisal * 100) : null;
  const grade = a && a.overall ? a.overall.grade : null;
  const mk = it.market || {};
  const loc = a && a.location;
  return `<details class="card">
    <summary>
      <span class="badge ${cls}">${label}</span>
      ${grade ? `<span class="grade ${esc(grade)}">${esc(grade)}등급</span>` : ""}
      <span>
        <div class="addr">${esc(it.addr)}</div>
        <div class="sub">${esc(it.court)} ${esc(it.case_no)} · 전용 ${it.area_m2||"?"}㎡ · 유찰 ${it.failed_bids}회 · 매각기일 ${d8(it.bid_date)}
        ${it.households ? ` · <b>${fmt(it.households)}세대</b>${it.kapt_name ? " ("+esc(it.kapt_name)+")" : ""}` : ""}</div>
      </span>
      <span class="price">감정가 ${fmtEok(it.appraisal)}<br><b>최저입찰가 ${fmtEok(it.min_price)}${rate ? " ("+rate+"%)" : ""}</b></span>
    </summary>
    <div class="body">
      ${a ? `
        ${a.overall ? `<h4>종합 판별표</h4>
        <table class="tbl">
          <tr><th>종합 등급</th><td><span class="grade ${esc(a.overall.grade)}">${esc(a.overall.grade)}</span>
            <span class="sub">${esc(GRADE_MEAN[a.overall.grade]||"")}</span><br>${gl(esc(a.overall.one_line||""))}</td></tr>
          <tr><th>권리 점수</th><td>${a.score!=null ? a.score+" / 100" : "-"}
            — <b>${esc(a.verdict)}</b> <span class="sub">${esc(VERDICT_MEAN[a.verdict]||"")}</span></td></tr>
          <tr><th>최저입찰가</th><td><b>${fmtEok(it.min_price)}</b> (감정가의 ${rate||"-"}%) — 이 금액 이상으로 써야 유효
            <span class="sub">· 입찰보증금 ${fmtEok((it.min_price||0)*0.1)}(10%)</span>
            ${mk.asking_min ? `<br>단지 매물호가 ${fmtEok(mk.asking_min)}~${fmtEok(mk.asking_max)} <span class="sub">(전 평형 혼합)</span>` : ""}</td></tr>
          ${loc ? `<tr><th>입지 점수</th><td><span class="loc"><span>역세권 <b>${loc.station}</b>/10</span><span>학군 <b>${loc.school}</b>/10</span><span>상권 <b>${loc.commerce}</b>/10</span></span></td></tr>` : ""}
        </table>` : ""}
        <h4>요약</h4><div>${gl(esc(a.summary||""))}</div>
        ${(a.risk_flags||[]).length ? `<div class="flags">${a.risk_flags.map(f=>`<span class="flag">${esc(f)}</span>`).join("")}</div>` : ""}
        ${(it.auto_checks||[]).length ? `<h4>자동 권리 체크리스트</h4>
          <ul class="chk">${it.auto_checks.map(c=>`<li class="${esc(c.status)}"><b>${gl(esc(c.label))}</b> — ${gl(esc(c.note))}</li>`).join("")}</ul>` : ""}
        <h4>말소기준권리 / 인수 권리</h4><div>${gl(esc(a.senior_rights||"-"))}</div>
        <h4>임차인 분석</h4><div>${gl(esc(a.tenant_analysis||"-"))}</div>
        ${(it.case_flags||[]).length ? `<h4>사건 진행 주의</h4>
          <ul class="chk">${it.case_flags.map(([l,st,n])=>`<li class="${esc(st)}"><b>${gl(esc(l))}</b> — ${gl(esc(n))}</li>`).join("")}</ul>` : ""}
        ${(it.bid_history||[]).length > 1 ? `<h4>기일별 이력</h4>
          <table class="tbl"><tr><th>매각기일</th><th class="num">최저매각가</th><th>결과</th></tr>
          ${it.bid_history.map(h=>`<tr${h.result==null?' style="font-weight:700"':''}>
            <td>${d8(h.date)}${h.result==null?' <span class="sub">(예정)</span>':''}</td>
            <td class="num">${fmtEok(h.min_price)}</td>
            <td>${h.result ? esc(h.result) : "-"}${h.sold_amount ? " "+fmtEok(h.sold_amount) : ""}</td></tr>`).join("")}
          </table>` : ""}
        ${(it.failure_signals || a.failure_reason) ? `<h4>왜 유찰됐나 <span class="sub">(유찰 ${it.failed_bids}회 · 감정가의 ${rate||"-"}%까지 내려옴)</span></h4>
          ${a.failure_reason ? `<div>${gl(esc(a.failure_reason))}</div>` : ""}
          ${it.failure_signals ? `<ul class="chk">${it.failure_signals.checks.map(c=>`<li class="${esc(c.status)}"><b>${gl(esc(c.label))}</b> — ${gl(esc(c.note))}</li>`).join("")}</ul>` : ""}` : ""}
        ${(it.redevelopment || a.redevelopment_note) ? `<h4>재건축 이슈${it.redevelopment && it.redevelopment.age ? ` <span class="sub">(준공 ${it.redevelopment.age}년차${it.redevelopment.newtown ? " · "+esc(it.redevelopment.newtown)+" 1기 신도시" : ""}${it.redevelopment.zone ? " · "+esc(it.redevelopment.zone)+" 투기과열지구" : ""})</span>` : ""}</h4>
          ${a.redevelopment_note ? `<div>${gl(esc(a.redevelopment_note))}</div>` : ""}
          ${it.redevelopment ? `<ul class="chk">${it.redevelopment.checks.map(c=>`<li class="${esc(c.status)}"><b>${gl(esc(c.label))}</b> — ${gl(esc(c.note))}</li>`).join("")}</ul>` : ""}` : ""}
        ${a.price_analysis ? `<h4>가격 분석 (시세 대비)</h4><div>${gl(esc(a.price_analysis))}</div>` : ""}
        ${loc && loc.comment ? `<h4>입지 총평 <span class="sub">(AI 지역지식 기반)</span></h4><div>${esc(loc.comment)}</div>` : ""}
        ${a.legal_notes ? `<h4>법률 분석</h4><div>${gl(esc(a.legal_notes))}</div>` : ""}
        <h4>입찰 의견</h4><div>${gl(esc(a.bid_opinion||"-"))}</div>
        ${a.bid_guide ? `<h4>입찰 가이드</h4><div>${gl(esc(a.bid_guide))}</div>` : ""}
        ${a.eviction_plan ? `<h4>명도 전략 (낙찰 후)</h4><div>${gl(esc(a.eviction_plan))}</div>` : ""}
        ${(a.must_verify||[]).length ? `<h4>입찰 전 필수 확인</h4><ul>${a.must_verify.map(v=>`<li>${gl(esc(v))}</li>`).join("")}</ul>` : ""}
        <h4>수익률 계산기</h4>
        <div class="calc">
          <div class="row">
            <label>입찰가(만원)<input id="c-bid-${it.key}" type="number" value="${Math.round((it.min_price||0)/1e4)}"></label>
            <label>예상 매도가(만원)<input id="c-sell-${it.key}" type="number" value="${Math.round(defaultSell(it)/1e4)}"></label>
            <label>대출비율(%)<input id="c-ltv-${it.key}" type="number" value="60"></label>
            <label>금리(%)<input id="c-rate-${it.key}" type="number" value="4.5" step="0.1"></label>
            <label>보유(개월)<input id="c-months-${it.key}" type="number" value="24"></label>
            <label>수리비(만원)<input id="c-repair-${it.key}" type="number" value="1500"></label>
            <label>명도비(만원)<input id="c-evict-${it.key}" type="number" value="500"></label>
            <label>보유주택<select id="c-multi-${it.key}"><option value="0">무주택/1주택</option><option value="1">다주택(중과 8%)</option></select></label>
            <label>목표수익률(%)<input id="c-target-${it.key}" type="number" value="15"></label>
          </div>
          <button class="tab on" onclick="runCalc('${it.key}')">세금·수익률 계산하기</button>
          <div id="calc-out-${it.key}"></div>
          <h4 id="rev-h-${it.key}" style="display:none">역산 입찰가</h4>
          <div id="rev-out-${it.key}" style="margin-top:4px"></div>
          <div class="note"><b>예상 매도가 기본값은 ${mk.asking_min ? "단지 호가 밴드 중간값(전 평형 혼합)" : "감정평가액"}입니다 — 반드시 해당 평형 실거래가로 바꿔서 계산하세요.</b><br>
          가정: 취득세 표준세율(6억↓1%, 6~9억 선형 1~3%, 9억↑3%, 다주택 8% 중과)+지방교육세+농특세(85㎡초과),
          법무비 0.1%, 매도 중개수수료 0.5%, 보유비용 연 0.2%, 양도세 근사(1년 미만 77% / 2년 미만 66% / 2년 이상 44%, 지방소득세 포함,
          기본공제·장특공제 미반영). 실제 세액은 세무사 확인 필요.</div>
        </div>
      ` : `<div class="sub">${esc(it.status_note||"아직 분석되지 않았습니다.")}</div>`}
      <h4>지도 · 현장 확인</h4>
      <div class="maplinks">${mapLinks(it).html}</div>
      <div class="sub" style="font-size:11.5px">${mapLinks(it).note} · 로드뷰로 건물 외관과 주변을, 실거래가로 시세를 확인하세요.</div>
      <h4>물건 정보</h4>
      <div class="sub">최선순위 설정: ${gl(esc(it.senior_lien||"-"))}<br>
      명세서 비고: ${gl(esc(it.remark||"-"))}<br>
      배당요구종기: ${(it.demand_deadlines||[]).map(d8).join(", ")||"-"}</div>
    </div>
  </details>`;
}
function esc(s){ return String(s??"").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])).replace(/\\r\\n|\\r|\\n/g,"<br>"); }
document.getElementById('glossary-list').innerHTML =
  Object.keys(GLOSSARY).map(k => `<dt>${k}</dt><dd>${GLOSSARY[k]}</dd>`).join("");
render();
</script>
</body>
</html>
"""


def _eok(won: int) -> str:
    return f"{won / 1e8:g}억"


def _price_label(f: dict) -> str:
    lo, hi = f.get("min_bid_price") or 0, f.get("max_bid_price") or 0
    if lo and hi:
        return f" · 최저가 {_eok(lo)}~{_eok(hi)}"
    if lo:
        return f" · 최저가 {_eok(lo)} 이상"
    if hi:
        return f" · 최저가 {_eok(hi)} 이하"
    return ""


def generate(items: list, config: dict, out_path: Path):
    f = config["filters"]
    data = {"generated_at": datetime.now().isoformat(), "items": items}
    page = (
        TEMPLATE
        .replace("__TITLE__", html.escape(config["web"]["title"]))
        .replace("__UPDATED__", datetime.now().strftime("%Y-%m-%d %H:%M"))
        .replace("__MIN_HH__", str(f["min_households"]))
        .replace("__MAX_FB__", str(f["max_failed_bids"]))
        .replace("__WINDOW__", str(f["bid_window_days"]))
        .replace("__AREA__", (f" · 전용 {f['min_area_m2']}㎡ 이상" if f.get("min_area_m2") else "")
                 + _price_label(f))
        .replace("__REGIONS__", (" · " + ", ".join(f["regions"])) if f.get("regions") else "")
        .replace("__DATA__", json.dumps(data, ensure_ascii=False)
                 .replace("</", "<\\/"))
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
