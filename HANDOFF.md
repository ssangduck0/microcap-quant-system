# 인수인계 노트 (2026-10-29 밤 압축본 · Claude Code 에서 갱신)

**읽는 법**: 이 파일은 '지금 상태 · 남은 일 · 결정 · 교훈 · 기능 색인'만 담는다(약 30KB). 10/29 까지의 긴 작업 기록(배포 확인 표 · 검증 숫자 · 사고 경위 전문)은 **`docs/archive/HANDOFF_2026-10-29_full.md`(99KB 원문 그대로)**, 그 전은 `docs/archive/인수인계서_2026-10-22.md`. 설계·검토 문서는 `docs/`(presim → `TASK_presim.md`, 실매매 → `broker_design_2026-10.md`·`toss_order_api_2026-10.md`, 차트 고수 → `chart_masters.md`, 토스 정책 → `toss_data_policy_audit_2026-10.md`). 새 기록은 이 파일에 짧게 적고, 길어지면 날짜별 archive 로 옮긴다.

## ☀️ 지금 상태(10/29 23:50 기준)
| 항목 | 상태 |
|---|---|
| 서버 코드 | **4532dc0**(23:53 배포 · Claude 읽기 전용 확인 끝) — presim 미완성 봉 수정 + 🛡 토스 정책 B안까지 반영. **배포 대기: 🛡 A안**(방문객 가격 → 전일 종가, 10/30 새벽 커밋) |
| 서비스 | 6개(scanner · dashboard 8501 · guest 8502 · collector · 터널 2) + 타이머 4개(cases 07:30 · backup 03:00 · chartex 06:40 · warm 10분) 정상 · 스캐너 사이클 ≈ 12~15분 · 오류 0 |
| 💵 실매매 | LIVE_TRADING **꺼짐(dry-run)** — 10/29 아침 결정 '당분간 유지'. 보유 0 · 킬 없음 · 동기화 60초 · 전략 piggy 만 |
| 🎲 presim | 운영 DB 에 사건 표 98,668건 · 오늘 판정 저금통 6종목(전부 🪙) · 배지 보임 · 내일 아침부터 순위 상위 10 추가 |
| 📰 뉴스 | 10/25~29 끊겼던 수집·번역 16:47 복구 → 1,027건(종목 있는 236 · 번역 113, 15분마다 10건씩 따라잡는 중) · 반응 기록(news_react)은 내일 아침 첫 갱신 |
| AI 비용 | 월 예산 3만 원 지갑 공유(관리 모드 값) · 오늘 번역 사고로 새던 하루 400원은 막음 |

**오늘(10/29) 한 일 한 줄씩**(상세 archive ☀️·🌤·✅ 표)
| 시각 | 일 |
|---|---|
| 06:27 | 💵 동기화 분리(60초) · 다른 전략 배관(기본 꺼짐) · 🧪 3일·5일 고가 목표(high3_20 AUC 0.686 · high5_30 0.706) 배포 |
| 14:42 | 💵 dry-run 결과 '그때 1주 샀다면'(`broker.dry_outcome`, `cases.py drysim`) 배포 |
| 16:25·16:47 | 📰 뉴스 사고 2개 수정(INSERT 열 수 불일치로 10/25 부터 0건 · 번역 답 잘림 무한 재시도 $0.44) + 📊 뉴스 반응 데이터 newsfx + 📰 화면 개편 + 🏁 순위 이력·'순위 연속' 가상매매 + 🎯 PICK scan 전체 죽던 None 버그 수정 배포 |
| 21:44 | 🎲 매매 전 시뮬레이션(두 겹) 배포 → 22:52 사용자 첫 실행(사건 표 98,668건 · 4분) |
| 23:11 | 🎲 장중 미완성 봉 제외 + 최근 사건 자가 치유(`RECENT_REDO`) 배포 · 운영 DB 로 동작 증명 |
| 23:40 | 🛡 토스 데이터 정책 점검 문서(`docs/toss_data_policy_audit_2026-10.md`) · HANDOFF 압축(99KB → 22KB, 원문 archive) |
| 00:10 | 🛡 **토스 정책 B안 구현**(사용자 선택 — 래빗스탁도 토스를 쓰냐는 질문에 '회사라 토스 API 상업 이용 불가 · 토스 언급 없음 · 로고는 FMP · 비로그인은 전일 종가'로 답한 뒤): `access.HIDDEN_PAGES` 에 movers·after, `HIDDEN_TABS` accum→close, `guest_block()` 안내 한 줄, `tabs.visible_items` 거르기, 화면 3곳 첫 줄 가드, 가이드 2곳. 테스트 test_guest_toss(새) + test_guest 1~4 · test_nav · test_accum_ui · test_mover · test_afterscalp_ui · test_closewatch_ui · test_lite · test_guide 모두 통과 |
| 23:53 | ✅ **B안 배포 확인**(읽기 전용): 파일 10개 md5 = 4532dc0 · 서비스 3개 23:53:42~44 재시작(오류 0) · 8501/8502 health ok · 방문객 서비스 QUANT_GUEST_ONLY=1 · 서버 배포본 테스트 test_guest_toss · test_nav · test_guest ALL OK. 남은 것: 사용자가 방문객 링크로 메뉴 눈 확인(📌 3번) |
| 10/30 00:40 | 🛡 **토스 정책 A안 구현**(사용자 승인 '범위 3곳 · 당일 계산 열 숨김 · 성과 공표 진입가 그대로'): 새 `guestpx.py`(`prev_close` = daily_prices 마지막 **확정** 봉 종가·등락, 16:20 ET 전엔 오늘 봉 제외, 2분 캐시) · 🏢 퀀트 스냅샷(방문객: 현재가 → '전일 종가($/원)' · 오늘 등락 → '전일 등락(%)' · '종가 기준일' 열 추가 · `HIDE_COLS` 8개 숨김 · 안내 캡션) · 종목 헤더/한 장 요약/가격 사다리(`glance.build(guest)` 가 price 를 전일 종가로, `price_label` 로 라벨 '전일 종가') · 🎯 PICK 격자(목표 대비 % 를 전일 종가로 재계산, 자료 없으면 '-') · 가이드 한 줄. 테스트 test_guest_px(새) · test_guest 스냅샷 열 검사 추가 · test_guest 1~4 · test_glance · test_pick30 · test_home_company · test_all · test_guide · test_lite · test_nav · test_screener · test_forensic_v2 · test_intel_dash · test_aisummary 모두 통과 · **배포 대기** |

## 📌 내일 아침(10/30) 확인할 것(5분)
1. 아침 작업 로그(07:30 시작, 약 70분): `ssh root@158.247.250.15 "journalctl -u quant-cases --since 07:00 --no-pager | grep -e 🎲 -e '뉴스 반응' -e 가상매매 -e dry"` → `🎲 사건 표(presim_ep): … 갱신 ≈1만`(자가 치유) · `🎲 매매 전 시뮬레이션: N종목`(저금통 6 + 순위 10 ≈ 16) · `뉴스 반응: N건 갱신` · 가상매매 줄에 순위 이력 저장 · 💵 dry-run 결과(10/28 FAMI·MRNO)가 처음 붙음.
2. 화면: 🐷 저금통 '🎲 시뮬' 열 · 🏁 순위 줄 배지 · 📇 스크리너 카드 ⑥(손절·목표 바꿔 🎲 버튼) · 📰 뉴스 접힌 줄 + 맨 위 '📊 뉴스 반응 통계' · 🧪 '🏁 순위 연속' 장부(첫 매수는 10/31 아침) · ⚙️ 💵 실매매 맨 아래 'dry-run 결과'.
3. ~~토스 데이터 정책 선택지~~ ✅ B안 23:53 배포·확인 끝 · ✅ **A안 구현(10/30 00:40, 배포 대기)** → 저녁에 `python deploy/deploy_from_pc.py` → 방문객 링크(관리 모드 👥)로 열어 ① 메뉴에 📈·🌙 없음 · 🧲 수급 탭 2개 ② 🏢 종목 › 퀀트 스냅샷 열이 '전일 종가($)'·'종가 기준일'이고 거래량 배수·진입참고 없음 ③ 종목 헤더 '전일 종가' ④ 🎯 PICK 격자 위 안내 캡션. 주인 화면은 그대로.

## 1. 할 일(우선순위 · 열린 것만)
1. 🛡 **토스 데이터 정책 — 방문객 사이트 노출**: `docs/toss_data_policy_audit_2026-10.md`. 정책은 "본인 매매 목적만 · 비상업적이라도 제3자 배포 금지". 방문객 24화면 중 🔴 원자료 그대로 3곳(📈 급상승/급하락 · 🧲 장마감 체크리스트 탭 · 🌙 애프터 스캘핑) · 🟡 가공값+당일 숫자 8곳 · 🟢 무관 13곳. 선택지 **A** 원자료 숨김+당일 숫자 가리기(저녁 1회) · **B** 원자료 3곳만 숨김 · C 동의문 강화 · D 방문객 중단. → **✅ 10/29 밤 사용자 'B안으로 진행' → 구현 · 23:53 배포 · 확인 끝(☀️ 표)**. 다음: **A안 계획안 ✅ 10/30 새벽**(점검 문서 7절 — 조사해 보니 실제 토스 당일 숫자는 🏢 퀀트 스냅샷 · 종목 헤더/요약 · 🎯 PICK 격자 **3곳**뿐, 홈·순위·3대 조건·매집·테마·가상매매는 야후) → ✅ 10/30 새벽 승인(범위 3곳 · 당일 계산 열 숨김 · 성과 공표 진입가 그대로) → **✅ 구현 완료(☀️ 표 00:40) · 배포 대기**.
2. 🎲 **presim 후속**: (a) 저금통용 기계적 저점 키('60일 저점 5% 안 + 희석 없음') — 오늘 저금통 6종목이 전부 '기준' 키라 판정에 정보가 없음. 판정 기준 추가라 **계획안 → 승인 → 구현(1저녁)**. (b) 2~3주 뒤 🏆 성과 공표 presim_g/c/r 비교(🔴 가 낮아야 맞음) → 🟢/🪙/🔴 문턱(COIN_GAP 10 · COIN_EV 1) 조정. (c) 장중 5분봉 모드는 보류(자료는 충분, 쓰임새 문제).
3. 💵 **실매매 1주 모드 재개 여부**: 1~2주 뒤 🧪 저금통 장부 + 💵 dry-run 결과로 판단 → 켜면 관리 모드 두 단계 스위치(확인 문구). 다음 단계 순서: 시간외 1주 테스트(LIVE_EXT_SESSIONS) → 순위·PICK 연결(LIVE_STRATEGIES). 체결 반영은 동기화 60초.
4. 🧠 **sigmodel B안(가상매매 문턱)**: 🔍 부검 탭 분위표에서 상·하위 적중 차이가 뚜렷해지면. 부검 표본 300건↑이면 공매·숏볼륨·장세·세션 특징 더해 재학습.
5. (선택) **3일 목표 10년 재수집** `cases.py build --years 10 --rebuild`(야후, 수십 분~1시간, 서버에서 사용자가) — 지금 3년치 47%(51,150건)로도 모델은 학습됨.
6. **날짜 되면 비교(코드 작업 없음)**: 11월 셋째~넷째 주 🧪 rank vs rank6 vs rank_stay(관리 모드 가상매매 비교표) → ⑥ 감점(❌ −10 · ⚠️ −5)을 본 순위 점수에 넣을지 · 2~4주 뒤 🏆 chart_* 적중률 · '📐 스승 눌림목' 승률 · AI PICK 확신별 · 검증 순위 · 스크리너 카드 적중률 · 🕰 '📐 허리 눌림+③'·숏 조합 적중률 · 11/15~22 공시 점수 두 방식 합치기 실험(텔레그램 예약 알림 옴).
7. **작은 후보(짬 날 때, 승인 필요한 건 표시)**: 수집기 `eventlab.label` 종목별 try/except · ONCO 병합 비율 '미확인' 정정(서버) · 2중 클래스(HYPR·RANI·HIT·RAIN) 표지는 파일별 XBRL 필요(보류) · 🧪 점수 검증 제안 ①모델 건강판 ②라이브 성공률 신뢰구간 ③입력값 갱신(승인 대기) · 📰 뉴스 통계 소급(과거 8-K 보도자료) · 🔍 부검 탭에 '아침 작업 실패 줄' 모아 보기 · ORB 는 타임머신 검증 뒤.

## 2. 사용자가 할 일
- ~~토스 데이터 정책 선택~~ ✅ B안 배포 끝 → 방문객 링크로 메뉴 눈 확인만(📌 3번).
- Vultr 콘솔 → 서버 → Backups 탭 자동 백업 켜져 있는지(R2 사본이 있어 필수는 아님).
- 텔레그램 토큰 재발급 여부(예전 채팅 노출) → 재발급 시 서버 `.env` TELEGRAM_TOKEN 수정 + `systemctl restart 'quant-*'`.
- 💵 재개할 때: 달러 매수가능 $0 이면 **$50 환전**(자동환전 없음) · 관리 모드 '계좌·달러 매수가능금액 확인(읽기만)' · 1주 왕복은 미국 정규장(한국 23:30~06:00).
- Claude 가 밤에 배포까지 하길 원하면 `.claude/settings.local.json`(git 제외)에 `{"permissions": {"allow": ["Bash(python deploy/deploy_from_pc.py)", "Bash(python deploy/deploy_from_pc.py *)"]}}` — Claude 는 자기 설정을 못 고침. 지금은 배포·서버 DB 쓰기·대시보드 비밀번호 입력을 Claude 가 못 하므로 그 명령은 HANDOFF 에 남긴다.

## 3. 지금 상태 한눈에(인프라)
| 영역 | 상태 |
|---|---|
| 코드 저장소 | GitHub `ssangduck0/microcap-quant-system` `main`(10/28 재구성, PR #1). 작업 마무리마다 커밋·푸시(배포는 `deploy_from_pc.py`). `.env`·DB·`__pycache__`·`.claude/` 는 .gitignore. PC 에 gh 설치·로그인 |
| 서버 | Vultr 서울 2vCPU/4GB(월 $24 + 자동 백업 $4.8 — 켜져 있는지 콘솔 확인 필요). 매일 03:00 DB 백업(`/home/quant/backup`, 14일) + **Cloudflare R2 사본**(버킷 `quant-backup`, 21일, `deploy/backup_db.sh` rclone, 열쇠 서버 `.env` `R2_*` · PC `클로드\토큰\r2.txt`). DB 888MB(10/29, presim 표 +62MB) |
| 보안 | SSH 키 전용 · ufw(SSH 만) · fail2ban · 자동 보안 업데이트 · Cloudflare Access(dash 만) · 서버 DNS 1.1.1.1 |
| 주소 | dash.sduckquant.com(주인, 비밀번호) / guest.sduckquant.com(방문객 링크 `?guest=토큰`, 동의·워터마크·기기 묶기·기간 만료) — Cloudflare 이름 있는 터널 quant-dash · quant-guest |
| AI 비용 | 월 예산 3만 원(관리 모드 값, 코드 기본 1만) 지갑 공유: AI PICK(하루 70~100원) · 뉴스 번역·공시 요약(Haiku) · 공시분석 v2(하루 3종목 ≈600원) · 스크리너 카드(≈100원/장) · 🤖 복기(주 1회 수 원). 관리 모드 '🤖 AI 비용' 표로 기능별 확인 |

## 4. 운영 명령 모음
- **배포**(PC PowerShell): `python deploy/deploy_from_pc.py`(미리 보기 `--dry-run`) — 묶기 → 올리기 → 덮어쓰기 → 재시작 → 캐시 데우기. Git Bash 의 ssh 는 키 문제로 안 됨(Claude 가 Bash 에서 쓸 땐 `/c/Windows/System32/OpenSSH/ssh.exe`).
- **상태·로그**: `ssh root@158.247.250.15 "systemctl list-units 'quant-*' --no-pager"` · `journalctl -u quant-scanner -n 30 --no-pager` · 아침 작업 `journalctl -u quant-cases --since 07:00 --no-pager`.
- **서버 1회 실행(항상 cd 먼저 — 상대 경로)**: `ssh root@158.247.250.15 "cd /home/quant/quant_system && sudo -u quant venv/bin/python -X utf8 cases.py presim"` — 같은 꼴로 `cases.py newsfx` · `cases.py drysim` · `cases.py backfill3d` · `winmodel.py fit` · `pagecache.py warm` / `status` · `toss_check.py` · `toxic.py 티커…` · `python chartex.py backfill`.
- **장중(한국 22:30~05:00 = 미국 정규장)에 수동 실행하면 오늘 일봉이 미완성** — presim·newsfx 는 자동으로 뺌(`cases.drop_incomplete_last_bar`), 다른 스크립트는 06:00 이후에.
- **테스트**: 하나 `DASH_PASSWORD= PYTHONUTF8=1 PYTHONIOENCODING=utf-8 QUANT_OFFLINE=1 python tests/test_x.py` → 마지막 줄 `ALL OK` · 전체 `bash tests/run_all.sh 1` … `5`(차례로, 동시 실행 X, 약 8~10분/부) · 서버에서 배포본으로: `cd /home/quant/quant_system && sudo -u quant env PYTHONUTF8=1 PYTHONIOENCODING=utf-8 DASH_PASSWORD= QUANT_OFFLINE=1 venv/bin/python tests/test_x.py`.
- **Claude 가 못 하는 것(앱 안전장치, 채팅 허락으로도 안 풀림)**: 배포 · 서버 DB 에 쓰는 명령 · `.claude/settings*.json` 수정 · 대시보드 비밀번호 입력. **할 수 있는 것**: ssh 읽기(상태·로그·`sqlite3 … mode=ro`) · 서버에서 임시 DB 테스트 · 운영 DB **복사본**으로 실험(`src.backup(dst)`, 끝나면 지움).
- PowerShell → ssh 에 안쪽 큰따옴표가 벗겨짐: 복잡한 건 스크립트 파일로 써서 `Get-Content -Raw 파일 | ssh root@… 'python3 -'`(또는 `'cd /home/quant/quant_system && sudo -u quant venv/bin/python -X utf8 -'`). grep 패턴에 한글·공백이 있으면 `-e 단어` 로 나눠서.

## 5. 기능 색인(모듈 → 한 줄 · 자세한 검증 숫자는 archive 2절)
| 영역 | 기능 · 모듈 | 핵심 한 줄 |
|---|---|---|
| 수집 | 스캐너 `scanner.py` · 우주 `universe.py` · `toss.py` | 토스 순위·1분봉·발행주식·환율·장 일정(토큰은 **서버 1개**) + 야후 보완. 사이클 ≈ 12~15분, `daily_snapshots`·`signals`·오늘 일봉 기록 |
| 수집 | 공시 `secfeed.py`(13D/G 양식명 'SCHEDULE 13D/G') · 상장유지 `listing.py`(Item 3.01 구간만, `void`) · 병합 `rsplit.py`(시행일·비율 규칙 추출) · 할인 전환 `toxic.py` | SEC 실시간 피드 → 태그·알림 · 🔁 병합 예정 · ⚠️ 할인 전환(≥40% 악성) |
| 수집 | 📡 ChartExchange `chartex.py`(Tier 1, `cx_shares` 403) · FINRA 숏볼륨·Reg SHO · 🪪 토스 거래 가능 `tradable.py` · 📊 매매강도 `flowsize.py`(웹소켓 체결, 구독 종목만) | 공매·FTD·숏볼륨·다크풀 재료 · ACTIVE 보통주 필터 |
| 수집 | 📰 뉴스 `news.py`(PR Newswire RSS, INSERT 열 이름 명시) · 🌐 번역 `translate.py`(Haiku, 묶음 10 · 8000 · `tr_tries` 3) · 📊 반응 `newsfx.py`(`news_react`: D 직전 종가 대비 당일 고가·종가·+1·+5일, 분류×등급 통계) | 분류·등급은 번역 때 붙음 → 종목 있는 뉴스 먼저 |
| 판정 | 🕰 타임머신 `timemachine.py`(3,000종목·2년, 컨닝 없음) | **RSI≤20 + 희석 없음**이 최고(40일 반등형 2026 +4.2% vs 기준 +0.1%) · 시간외 포함 시 +10% 급등 1.7배 더 잡힘 · 숏 조합 9개(공개 지연 반영) |
| 판정 | ✅ 3대 조건 `setup3.py` · 🏁 종합 순위 `rank.py`+`pressure.py`(`score6/rank6` ⑥ 감점은 보조 열, `rank_hist` 상위 50) · 🎯 PICK `pick30.py`(⑥ ❌ 탈락, '유력'은 드묾) | 순위 계산 19.5→5.6초(WAL 1회·conn 재사용) · 캐시 `pagecache` |
| 판정 | 🐷 저금통 `piggy.py`(자동 담기·빼기, 주의사항 ①~⑦) · 주식수 `shares.py`(SEC 분기 표지 이력 `shares_hist`, ⑥ **+20% 유지** · 10~20% ⚠️) | ⑥ 검증: ❌ 60일 중앙값 −16% vs ✅ −5%, 급등 기회는 같음(`docs/studies/`) |
| 판정 | 📐 차트 고수 `chartview.py`(A 엔진 · B 화면 · C 신호 `chart_signals` · D 🚦 장세 `regime.py` · E 🧪 master) · `docs/chart_masters.md` | 기준봉·채널·되돌림·매물대·이평·파라볼릭·다이버전스 · 실시간 경고(CHART_ALERTS) |
| 판정 | 🎲 매매 전 시뮬레이션 `presim.py`·`presim_ui.py`(두 겹 · `presim_ep` 98,668건 · `presim_log` · 아침 자동 · 배지 3곳 · 📇 ⑥ · 🏆 출처 3개 · `RECENT_REDO` 자가 치유) | 전체 과거: 기준 익절 19%·손절 66%·EV −0.1% vs ⭐1 21%·66%·**+0.9%** — 신호 우위 작지만 방향 맞음 · `docs/TASK_presim.md` |
| AI | 🤖 AI PICK `aipick.py`(Sonnet, 예산 지갑 `call_claude`·`_add_spend`·`budget_left_krw`) · 🧾 공시분석 `forensic_ai.py`(11절 + SUMMARY_JSON → 📰 한 장 요약 `summary_ui.py`·규칙 `clock.py`) · 📝 공시 요약 `secdigest.py` · 📇 스크리너 카드 `screener.py` | 자동 대기열 하루 3종목 · 📰 요약은 아침 자동 |
| AI | 🔍 부검 `autopsy.py`(놓친 펌핑·실패 신호 특징) → 🧠 신호 승률 `sigmodel.py`(A안, 토요일 재학습, p30 AUC 0.73, 판정 기준 불변) → 🤖 복기 `review.py`(주 1회 Haiku, 규칙 후보는 제안만) | '우리만의 AI' 1→2→3단계 완료 · 4단계 = 💵 |
| 검증 | 🏆 성과 공표 `scoreboard.py`(출처별 적중, chart_*·toxic_*·cx_*·presim_g/c/r …) · 🧪 점수 검증 `winmodel.py`(high_20 0.739 · high3_20 0.686 · high5_30 0.706, `cases.backfill_3d`) · 📒 매매 일지 `journal.py` · 🔬 이벤트 연구 `eventlab.py` · 📚 과거 사례 `cases.py build` | 과거 판정은 그날 이전 정보만 |
| 검증 | 🧪 가상매매 `papertrade.py`(전략 rank·rank6·rank_stay·pick·close·piggy·after·master, 규칙은 매수 때 스냅샷, 청산 = 먼저 닿은 쪽, 세션 기록 보완) | 비교 시점 11월 셋째 주(1절 6번) |
| 실매매 | 💵 `broker.py`·`toss.py`·`broker_ui.py`(1주 모드 B안: dry-run 기본 · 스캐너 안에서만 주문 · 안전장치(종목 $100 · 하루 3건 · 3종목/$500 · 일손실 −$50 킬 · 금지 목록) · OCO · 동기화 60초 · 요청 표 · `dry_outcome`) | 10/29 01시 첫 운영 3종목 왕복 −1.4센트(체결 3/3) → 사고 뒤 킬 → **dry-run 유지** · 설계 `docs/broker_design_2026-10.md` |
| 화면 | `dashboard.py` PAGES 29(묶음 홈·오늘·발굴·선별·종목·추적·관리) · `tabs.py`(방문객 탭 거르기) · `lite.py`(휴대폰 간략·옛 주소 변환) · 👥 방문객 `access.py`(HIDDEN_PAGES 7 · HIDDEN_TABS · `guest_block`) · `guestpx.py`(방문객 가격 = 전일 종가, 토스 정책 A안) · 🔍 차트 팝업 `chartpop.py`(모든 차트 공통) · 🔥 캐시 `pagecache.py`(quant-warm 10분) · 📖 가이드 `guide_content.py`(39절) | 화면 하나 = `xxx_ui.render()` |
| 화면 | 🏠 홈(브리핑·🚦 장세 `macro_ui`) · 🔔 공시 알림(+📨 보낸 알림 `alert_log`) · 📈 급상승/급하락 `mover.py` · 🧲 수급(매집 `accum`·세력 `pumpsetup`·장마감 체크리스트 `closewatch`) · 🏷 테마 · 💰 펀드스캔 · ⚡ EFFECT · 👤 내부자 · 📛 Reg SHO · 🧨 스퀴즈 · 🕶 다크풀 `darkpool.py` · 🏦 대량 보유 · 🏢 종목(헤더 칩 ⑥·⛔ 등, 📊 매매강도) · 🌙 애프터 스캘핑 `afterscalp.py` · 📅 일정 · 📝 노트 · ⚙️ 관리(설정 → DB meta, 🤖 AI 비용, 🔥 캐시, 💵 실매매) | 토스 자료가 보이는 화면 분류는 `docs/toss_data_policy_audit_2026-10.md` 4절 |
| 운영 | 🔌 오프라인 테스트 `config.OFFLINE`(임시 DB 자동 · `QUANT_OFFLINE=1`) · ☁️ R2 백업 `deploy/backup_db.sh` · 타이머 설치 `deploy/install_*_timer.sh` · 서버 문서 `deploy/README_SERVER.md` | 테스트 145개 파일 · 전체 5부 약 8분 |

## 6. 결정해 둔 것(바꾸려면 사용자 확인)
- 폭풍의 눈(GEM)은 타임머신 조건으로만 · D-Day·커뮤니티 안 만듦 · 급상승/급하락 실시간은 Massive 연결 때.
- SURG 같은 ATM 활성 종목은 후보 제외(희석 부재가 최우선) · 🐷 ⑥ 주식수 변동 기준 **+20% 유지**(10~20% 는 ⚠️ 표시만).
- 수입물가는 한국 IP 에서 BLS·FRED 막힘 → 관리 모드 수동 입력.
- 💵 실매매: B안 '1주 모드'(저금통 신호마다 1주 · OCO) · 10/29 아침 'dry-run 유지' · 11월 말 $100 여부.
- 🎲 presim: 일봉 모드 먼저(장중 5분봉 보류) · 두 겹(같은 신호 전체 과거 + 종목 250일) · 기본값 계좌 500만 · 최대 손실 5만 · 순위 상위 10 · 방문객 배지 보임 · 이름은 '🎲 매매 전 시뮬레이션'(🕰 타임머신과 구분).
- 🧠 sigmodel 은 판정 기준을 바꾸지 않음(B안은 검증 뒤) · 🤖 복기 규칙 후보는 사람이 🕰 으로 검증한 뒤에만.
- 외부 자료(10/29, 방구석 프로 RSC-04 · GitHub day-trader-skill, 코드는 안 가져옴): 🎲 시뮬레이션·수량 계산 가져옴 ✅ · 리스크 규칙은 이미 있음 · ORB 는 검증 뒤 🟡 · 15:55 청산·펠로시·알파카 ❌. 외부 스킬을 설치해 볼 땐 먼저 "외부 전송·파일 삭제·주문 기능이 있는지 검토".
- 사용자 요청(10/29, 메모리에도 저장): 내가 보낸 자료에 더 좋은 방법이 있으면 **먼저 말하고**(약점 → 대안 → 비용) 결정한 것을 만든다.

## 7. 알아 둘 사고·교훈(전문은 archive 6절)
- 🎲 **장중 수동 실행의 미완성 봉**(10/29): 스캐너가 장중에 오늘 일봉을 진행 중 값으로 계속 덮어씀 → 일봉으로 판정·표를 만드는 코드는 `cases.drop_incomplete_last_bar`(16:20 ET 전 오늘 봉 제외). 아침 작업은 마감 뒤라 무관.
- 🎯 **한 종목의 None 이 전체를 죽임**(10/29): `runway.label` 의 `:.1f` 가 None → `pick30.scan()` 통째로 실패 → PICK 가상 매수가 매일 조용히 실패. 형식 지정 앞 None 검사 · 종목 루프는 종목마다 try/except · 아침 로그 '실패' 줄은 다음 날 꼭 다시 보기.
- 📰 **열 추가 뒤 INSERT 깨짐**(10/29): `ALTER TABLE ADD COLUMN` 뒤 열 이름 없는 `INSERT … VALUES (?,…)` 는 전부 실패 → INSERT 는 **항상 열 이름** · 외부 받기 실패는 meta 뿐 아니라 `log.warning` 으로도(닷새 동안 몰랐음).
- 🌐 **AI 묶음 답 잘림 = 0건 + 무한 재시도**(10/29): 묶음 작게 · 출력 한도 넉넉히 · 잘린 JSON 에서 온전한 항목 건지기 · 시도 횟수 기록 · '0건' 반복이면 경고. 🤖 AI 비용 표에서 기능별 건수 대비 성과 가끔 보기.
- 💵 **실매매 첫 운영 사고**(10/29 01:15): 사용자가 같은 계좌에서 직접 판 POM 386주 기록을 우리 1주 OCO 체결로 오인 → −$115.80 기록 → 일손실 킬. 실제 피해 없음. **우리 것이 아닌 주문을 추정하지 말고 조건주문 ID 로 확인** · 꺼져 있어도 `sync` 는 계속 추적 · 장부 정리 `fix_pom_20261029.py`.
- 🧪 **공용 표를 읽는 화면은 자기 것만 골라 읽기**(10/28): 🧠 sigmodel 이 `models` 표에 들어오자 점수 검증 탭 KeyError.
- 🔌 **테스트가 진짜 인터넷·Claude 를 부르고 있었음**(10/28): 느린 9개의 원인은 계산이 아니라 HTTP 95회(진짜 Claude 호출 포함) → `config.OFFLINE`. 새 주기 작업은 `http_get`/`post`/`download` 인자로 가짜를 받게 · 테스트가 갑자기 느려지면 인터넷부터 의심.
- 🧪 가상매매 판정의 한계: 1분봉이 없는 구간은 세션 고·저가로 보완(같은 세션 안 순서 모름 → 둘 다면 손절) · 세션 최저가는 10/27 뒤부터 · 애프터 전략 마감가는 `after_signals.exit_price`.
- 전체 테스트는 5부를 **차례로**(동시에 돌리면 100초 제한에 빈 줄 실패) · 빈 줄이 나오면 진짜 실패 · 화면 테스트가 전부 빈 화면이면 `.env` 의 DASH_PASSWORD 때문(`DASH_PASSWORD=` 로 비움) · `test_glance` 는 run_all.sh 가 임시 폴더 복사 처리.
- 배포는 PowerShell 에서(Git Bash ssh 는 키가 ssh-agent 에만) · 예전 zip 이 올라간 실수 2번 → `deploy_from_pc.py` 로만 · PC 창/서버 창 혼동 → Claude 가 직접 · 같은 작업 공간은 한 번에 한 세션만.
- Sonnet 5.5 는 생각 토큰이 한도를 먹어 빈 답 → `effort="medium"` + max_tokens 넉넉히(CLAUDE.md) · `.env` 끝 줄바꿈 없이 덧붙이면 키가 망가짐.
- DB 잠김(`database is locked`): 30초 넘는 쓰기 트랜잭션(소급 스크립트)이 원인 → 소급은 장 밖에, 길면 commit 나눠서 · 수집기 label 종목별 try/except 는 후보.
- 📥 **옛 zip 을 받으면 덮어쓰지 말 것**(10/29): START_HERE 와 함께 온 zip 이 10/26 옛 코드였음 → 새 문서(HANDOFF_presim)만 가져오고 코드는 비교 뒤 판단.
- 🏷 피드가 0건이면 양식명부터(EDGAR 가 13D/G 이름을 바꿔 피드가 비었던 일) · ChartExchange Tier 1 은 shares 엔드포인트 403.
