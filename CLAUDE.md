# 초소형주 퀀트 대시보드 — Claude Code 작업 규칙

## 사용자와 대화
- **항상 한국어**로 답한다(영어 답을 싫어함). 쉬운 말로, 표를 활용해 짧게.
- 사용자는 평일 직장인이라 저녁에 작업한다. 서버·주식 용어는 처음 나올 때 풀어서 설명.
- 큰 변경(화면 구조·판정 기준·비용이 드는 기능)은 **먼저 계획을 보여 주고 승인**받은 뒤 진행.
- 지금 상태·결정·남은 일은 `HANDOFF.md` 를 먼저 읽는다. `HANDOFF_*.md`(추가 인수인계서)가 있으면 그것도 읽고, 맨 위 진행 순서를 따른다.
- 고치기 전에 **읽고 확인 → 보고 → 승인 → 계획 → 승인 → 구현** 순서. 문서와 실제 코드가 다르면 실제 코드를 믿고 차이를 보고한다.

## 프로젝트
- Streamlit 대시보드(`dashboard.py`) + 스캐너(`scanner.py`) + 아침 갱신(`cases.py update`) + 이벤트 수집기(`eventlab.py run`)
- DB: SQLite. 서버 `/home/quant/data/quant.db`, PC 는 `C:\quant_data\quant.db`(PC 는 예비 — 지금 운영은 서버)
- 설정: `config.py`(+ `.env`, 관리 모드에서 바꾸는 값은 DB 에 저장). 비밀값은 `.env` 에만 — **절대 커밋·출력·zip 하지 말 것**
- 화면 하나 = `xxx_ui.py` 의 `render()` 를 `dashboard.py` 의 `for _ in page("키"):` 블록이 부름. 메뉴 목록은 `dashboard.py` 의 PAGES

## 테스트 (코드를 고치면 반드시)
- 기능마다 `tests/test_*.py`(가짜 데이터·가짜 API·Streamlit AppTest). 새 기능엔 새 테스트를 같이 만든다.
- 하나만: `python tests/test_screener.py` → 마지막 줄 `ALL OK`
- 전체(5부분): `bash tests/run_all.sh 1` … `5` (Git Bash). 실패한 파일만 줄로 나온다.
- 테스트는 인터넷 없이 돌아가야 한다(야후·SEC·Claude 는 가짜로). `QUANT_DB` 가 임시 폴더면 `config` 가 **오프라인 모드**를 자동으로 켬(requests 전부 차단·Claude/텔레그램 키 비움·야후 건너뜀, `QUANT_OFFLINE=1` 로 강제). 진짜 인터넷·API 가 필요한 코드는 `http_get`/`post`/`download` 인자로 가짜를 넘겨 테스트.

## 서버 반영
- 서버: Vultr 서울 `root@158.247.250.15`(Ubuntu 24.04). 코드 `/home/quant/quant_system`, 실행 사용자 `quant`, 파이썬 `/home/quant/quant_system/venv/bin/python`
- 배포: **`python deploy/deploy_from_pc.py`** (묶기 → 올리기 → 덮어쓰기 → 재시작 → 상태). 미리 보기: `--dry-run`
- 서비스: quant-scanner · quant-dashboard(8501) · quant-guest(8502) · quant-tunnel · quant-guest-tunnel · quant-collector · quant-cases.timer(화~토 07:30) · quant-backup.timer(03:00)
- 상태: `ssh root@158.247.250.15 "systemctl list-units 'quant-*' --no-pager"` · 로그: `journalctl -u quant-scanner -n 30 --no-pager`
- 서버에서 직접 실행할 땐: `sudo -u quant /home/quant/quant_system/venv/bin/python /home/quant/quant_system/<파일>.py`
- 주소: https://dash.sduckquant.com (Cloudflare Access + 비밀번호) · https://guest.sduckquant.com (방문객)
- pandas 는 3.0.x 고정(3.1 은 미검증).

## 지켜야 할 것
- **토스 API 는 한 곳(서버)에서만** — PC 에서 스캐너를 켜지 말 것(토큰 충돌).
- 서버 `.env`·DB 를 지우거나 덮어쓰지 말 것. DB 구조 변경은 `CREATE TABLE IF NOT EXISTS`·`ALTER TABLE ADD COLUMN` 로만(기존 데이터 보존).
- AI(Claude API) 비용은 `aipick` 의 월 예산 지갑(`AI_MONTHLY_BUDGET_KRW`, 기본 5만 원)을 모든 기능이 같이 쓴다. 새 AI 기능도 `aipick.call_claude` · `aipick._add_spend` · `budget_left_krw` 를 쓸 것.
  - Sonnet 5.5 는 생각(thinking)이 기본 → `effort="medium"` + `max_tokens` 넉넉히(안 그러면 빈 답). Haiku 5.5 는 `thinking={"type":"disabled"}`.
- 과거 판정(타임머신·성과 공표)은 **그날 이전 정보만**(컨닝 금지).
- 판정 기준·검증 결과를 바꾸면 이유를 코드 주석에 남기고 사용자에게 숫자로 설명.
