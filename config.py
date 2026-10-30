"""설정 모음. 비밀값(토큰 등)은 코드에 쓰지 말고 환경변수 또는 .env 파일로 관리하세요."""
import os
import warnings

warnings.filterwarnings("ignore", message=r".*inplace keyword.*")  # pandas 3.1 + yfinance 경고(동작에는 영향 없음)
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv  # 선택 사항 (pip install python-dotenv)
    # 실행한 폴더가 아니라 항상 이 프로젝트 폴더의 .env 를 읽는다(다른 폴더에서 켜면 .env 를 못 찾아 빈 DB 를 새로 만드는 문제 방지)
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

# ----------------------------------------------------------------- 🔌 오프라인(테스트) 모드 — 2026-10-28
# 테스트는 인터넷 없이 돌아야 한다(CLAUDE.md). 그런데 scanner.run_cycle 의 주기 작업(FRED 레짐·나스닥 Reg SHO·수입물가·뉴스 번역)이 테스트 안에서
# 진짜 인터넷을 95번 부르고(느린 테스트 9개의 원인: 1회 120초) 번역은 .env 의 진짜 키로 Claude 를 실제 호출해 돈이 나갔다.
# → QUANT_OFFLINE=1 이거나(run_all.sh) QUANT_DB 가 임시 폴더 아래면(모든 테스트): 돈·메시지가 나가는 키를 비우고 requests 의 모든 호출을
#   즉시 ConnectionError 로 막는다(코드의 try/except 가 "못 받음" 으로 처리 → 느린 타임아웃 대신 0초). 야후는 market 이 config.OFFLINE 을 보고 건너뜀.
#   QUANT_OFFLINE=0 이면 임시 DB 라도 켜지 않음(서버·PC 운영 DB 는 임시 폴더가 아니라 영향 없음).
def _under_tmp(p: str) -> bool:
    try:
        import tempfile
        return bool(p) and Path(p).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
    except Exception:  # noqa: BLE001
        return False


OFFLINE = os.environ.get("QUANT_OFFLINE") == "1" or (os.environ.get("QUANT_OFFLINE") != "0" and _under_tmp(os.environ.get("QUANT_DB", "")))
if OFFLINE:
    for _k in ("ANTHROPIC_API_KEY", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"):
        os.environ[_k] = ""
    try:
        import requests as _rq

        def _offline_request(self, method, url, *a, **k):
            raise _rq.exceptions.ConnectionError(f"오프라인(테스트) 모드: 인터넷 호출 차단 — {method} {url}")

        _rq.sessions.Session.request = _offline_request
    except Exception:  # noqa: BLE001
        pass

_DEFAULT_DB = Path(r"C:\quant_data\quant.db") if os.name == "nt" and Path(r"C:\quant_data\quant.db").exists() else BASE_DIR / "quant.db"
DB_PATH = Path(os.environ.get("QUANT_DB") or _DEFAULT_DB)  # .env 에 QUANT_DB 가 없어도 기존 C:\quant_data\quant.db 가 있으면 그것을 씀
MANUAL_TICKERS_FILE = BASE_DIR / "manual_tickers.txt"

# SEC는 User-Agent에 "이름 이메일" 형식을 요구합니다. 예) SEC_USER_AGENT="Hong Gildong hong@example.com"
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()

# 텔레그램 알림(선택). 둘 다 설정되어 있을 때만 전송합니다.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# 토스증권 공식 Open API (선택). 둘 다 있어야 켜집니다. TOSS_ENABLED=0 으로 끌 수 있습니다.
TOSS_CLIENT_ID = os.environ.get("TOSS_CLIENT_ID", "").strip()
TOSS_CLIENT_SECRET = os.environ.get("TOSS_CLIENT_SECRET", "").strip()
TOSS_BASE_URL = os.environ.get("TOSS_BASE_URL", "https://openapi.tossinvest.com").strip()
TOSS_ENABLED = bool(TOSS_CLIENT_ID and TOSS_CLIENT_SECRET) and os.environ.get("TOSS_ENABLED", "1") != "0"

# 거래량 배수의 분자(오늘 거래량) 출처. 분모(20일 평균 일거래량)가 yfinance 일봉이라 기본은 yfinance 1분봉 합.
# 토스 1분봉 거래량은 종목마다 yfinance 의 60~90% 수준이라(volume_check.py 로 확인) 섞어 쓰면 배수가 낮게 왜곡됩니다.
VOLUME_SOURCE = os.environ.get("VOLUME_SOURCE", "yahoo").strip().lower()   # "yahoo" | "toss"

# 승률 점수(승률 모델). 모델은 `python winmodel.py fit` 으로 학습해 DB에 저장됩니다.
WIN_MODEL = os.environ.get("WIN_MODEL", "high_10")      # 스캐너가 스냅샷에 기록할 모델 (라벨_목표%: high_10 = 다음날 고가 +10%)
DILUTION_ADJUST = os.environ.get("DILUTION_ADJUST", "1") != "0"
# 희석 상태별 확률 보정 배수. **가정값**입니다 — 과거 가격 데이터만으로는 시점별 희석 상태를 알 수 없어 학습하지 못했습니다.
# 대시보드 '점수 검증' 탭의 '희석 상태별 실측 성공률'이 쌓이면 그 값으로 교체하세요.
DILUTION_MULT = {"CLEAN": 1.0, "ELOC": 0.9, "OFFERING": 0.85, "CB": 0.75, "ATM": 0.6, "UNKNOWN": 0.9}

SCAN_INTERVAL_SEC = int(os.environ.get("SCAN_INTERVAL_SEC", "300"))
MAX_TICKERS = 80                  # (manual 모드) 한 사이클에 보는 최대 종목 수
MIN_DRAWDOWN_PCT = -12.0          # 20일 고점 대비 낙폭이 이보다 얕으면 제외
DILUTION_REFRESH_HOURS = 6        # SEC 희석 판별 재검사 주기
DILUTION_RETRY_HOURS = 0.5        # '확인 불가'였던 종목 재시도 주기
FUNDAMENTALS_REFRESH_HOURS = 24   # float/거래소 정보 갱신 주기
SIGNAL_MIN_MOVE_PCT = 5.0         # 직전 신호 대비 이 이상 움직여야 신호 로그를 추가
ALERT_MIN_PUMP_SCORE = 70.0       # 텔레그램 알림 최소 점수


# ---- 나스닥 전체 스캔 설정 ----
# "nasdaq"      : 나스닥 상장 전체 (ETF·테스트·워런트·우선주 등 제외)
# "nasdaq+amex" : 나스닥 + NYSE American
# "manual"      : manual_tickers.txt + 토스/스크리너 (기존 방식)
SCAN_UNIVERSE = os.environ.get("SCAN_UNIVERSE", "nasdaq").strip().lower()
UNIVERSE_CACHE_HOURS = 24
DAILY_CHUNK = 100                 # 1단계 일봉 다운로드 묶음 크기
MIN_PRICE_USD = 0.05              # 1단계 필터: 가격 범위
MAX_PRICE_USD = 20.0
MIN_AVG_DOLLAR_VOL = 100_000      # 1단계 필터: 20일 평균 거래대금(달러) 최소값 (거의 거래 없는 종목 제외)
STAGE1_MARGIN_PCT = 5.0           # 1단계는 일봉 기준이라 낙폭 기준을 이만큼 느슨하게 통과시킴
MAX_MARKET_CAP_USD = int(os.environ.get("MAX_MARKET_CAP_USD", "300000000"))  # 이보다 큰 종목은 정밀 분석에서 제외(0=끄기). 토스 발행주식수 x 현재가로 근사
# 장마감 체크리스트(토스 기준) — 정규장 중 스캐너가 후보 종목의 호가·1분봉·SEC 공시를 매 사이클 기록한다
CLOSE_WATCH_TOP_N = int(os.environ.get("CLOSE_WATCH_TOP_N", "20"))             # 토스 급하락 순위 몇 위까지(장마감 체크리스트 대상)
CLOSE_WATCH_FREEZE_MIN = int(os.environ.get("CLOSE_WATCH_FREEZE_MIN", "60"))   # 정규장 마감 몇 분 전에 대상을 고정할지
CLOSE_WATCH_MIN_DROP = float(os.environ.get("CLOSE_WATCH_MIN_DROP", "-10"))   # 오늘 등락이 이 값 이하인 종목만 추적(넓게 잡고 화면에서 조정)
TOSS_WS_ENABLED = os.environ.get("TOSS_WS_ENABLED", "1") != "0"               # 토스 실시간 웹소켓(체결강도·호가 추이). websockets 패키지가 없으면 자동으로 꺼짐
FINTEL_API_KEY = os.environ.get("FINTEL_API_KEY", "").strip()                 # (선택) Fintel API: 공매도 잔고 등 보조. 공매도 거래량·대차는 FINRA·IBKR(무료)가 기본
HALTS_ENABLED = os.environ.get("HALTS_ENABLED", "1") != "0"                   # 거래정지(LULD) — 업킷 API 기본, 실패 시 나스닥 RSS
SECFEED_ENABLED = os.environ.get("SECFEED_ENABLED", "1") != "0"        # 🔔 SEC 실시간 공시 피드(우리 종목만)
SECFEED_ENRICH_PER_CYCLE = int(os.environ.get("SECFEED_ENRICH_PER_CYCLE", "15"))   # 사이클당 본문 키워드 판정 건수
INSIDER_PER_CYCLE = int(os.environ.get("INSIDER_PER_CYCLE", "20"))       # 👤 사이클당 Form 4 원문 읽기 건수
SECFEED_ALERTS = os.environ.get("SECFEED_ALERTS", "1") != "0"          # 워치리스트·저금통 종목 새 공시 텔레그램 알림
AFTER_SCALP_ENABLED = os.environ.get("AFTER_SCALP_ENABLED", "1") != "0"   # 🌙 애프터 스캘핑(스승님 꿀팁) 판정
AFTER_TOP_N = int(os.environ.get("AFTER_TOP_N", "30"))                     # 애프터: 토스 실시간 거래량 상위 몇 위까지 볼지
AFTER_ALERTS = os.environ.get("AFTER_ALERTS", "1") != "0"                  # 애프터 진입 구간·매도 마감 텔레그램 알림
FLOWREAD_ALERTS = os.environ.get("FLOWREAD_ALERTS", "1") != "0"      # 📈 분산·털기(스승님 꿀팁) 신호 텔레그램 알림
SETUP_MAX_PER_CYCLE = int(os.environ.get("SETUP_MAX_PER_CYCLE", "5"))   # 🕵️ 세력·셋업: 사이클당 새로 분석할 종목 수(종목당 하루 한 번)
SHORTFLOW_ALERTS = os.environ.get("SHORTFLOW_ALERTS", "1") != "0"    # 🩳 공매도 흐름(스승님 꿀팁) ②③④ 단계 텔레그램 알림
PRESSURE_REPORTS_PER_DAY = int(os.environ.get("PRESSURE_REPORTS_PER_DAY", "25"))   # 🧭 매일 아침 압박 후보 종목 리포트 생성 상한
ACCUM_DAILY = os.environ.get("ACCUM_DAILY", "1") != "0"              # 🧲 매일 아침 매집 의심 분석
RSPLIT_DAILY = os.environ.get("RSPLIT_DAILY", "1") != "0"            # 🔁 매일 아침 최근 1년 분할 기록 갱신(병합 후 레이더)
TIER_HOLD_DAYS = int(os.environ.get("TIER_HOLD_DAYS", "40"))         # ⭐ 깊은 과매도+희석 없음(검증 순위): 반등형 보유 기간(거래일)
#   🕰 보유 기간 검증(+30% 익절·−20% 손절): 1순위 2026년 5일 +1.3% · 10일 +1.8% · 20일 +2.6% · 40일 +4.2% — 앞 기간(~2025)도 같은 순서 → 40일
TIER_TARGET = float(os.environ.get("TIER_TARGET", "30"))              # 익절 %
TIER_STOP = float(os.environ.get("TIER_STOP", "-20"))                 # 손절 %
SEC_DIGEST = os.environ.get("SEC_DIGEST", "1") != "0"                 # 📝 공시 한국어 요약·병합 일정·13D/13G(Haiku, AI 월 예산 안에서)
NEWS_TRANSLATE = os.environ.get("NEWS_TRANSLATE", "1") != "0"         # 🌐 뉴스 한국어 번역(Haiku 5.5, AI 월 예산 안에서)
PRESIM_ACCOUNT_KRW = float(os.environ.get("PRESIM_ACCOUNT_KRW", "5000000"))   # 🎲 매매 전 시뮬레이션: 계좌 크기(원) — 수량 계산용(2026-10-29 사용자 기본값)
PRESIM_MAX_LOSS_KRW = float(os.environ.get("PRESIM_MAX_LOSS_KRW", "50000"))   # 🎲 한 번 매매의 최대 손실(원)
PRESIM_REGIME_VERDICT = os.environ.get("PRESIM_REGIME_VERDICT", "1") != "0"   # 🎲 대표 판정에 장세 반영(2026-10-30 C안): 2년 전체 판정과 '오늘과 같은 장세 날만' 판정 중 더 조심스러운 쪽
PRESIM_TOP_N = int(os.environ.get("PRESIM_TOP_N", "10"))                      # 🎲 아침 자동 실행: 종합 순위 상위 몇 개까지(0 = 안 함)
AI_PICK_ENABLED = os.environ.get("AI_PICK_ENABLED", "1") != "0"       # 🤖 AI PICK(아침 갱신 때 하루 한 번 Claude 판단)
AI_PICK_MODEL = os.environ.get("AI_PICK_MODEL", "claude-sonnet-5-5").strip()
AI_MONTHLY_BUDGET_KRW = float(os.environ.get("AI_MONTHLY_BUDGET_KRW", "50000"))  # 월 AI 예산(원) — AI PICK·뉴스 번역·서버 공시분석 합계, 넘으면 실행하지 않음
FORENSIC_AI = os.environ.get("FORENSIC_AI", "1") != "0"               # 🧾 서버 자동 공시분석(덕구 포렌식, 아침 갱신 때 대기열에서)
FORENSIC_PER_RUN = int(os.environ.get("FORENSIC_PER_RUN", "3"))       # 한 번에 분석할 종목 수
FUNDSCAN_AI_PER_DAY = int(os.environ.get("FUNDSCAN_AI_PER_DAY", "20"))  # 💰 펀드스캔 AI 보조 추출 하루 상한(C단계 2026-10-27)
CHARTEXCHANGE_RPM = int(os.environ.get("CHARTEXCHANGE_RPM", "55"))         # 📡 ChartExchange 분당 요청 상한(Tier 1 = 60 · Tier 2 = 250). 키는 .env CHARTEXCHANGE_API_KEY
AI_PICK_MAX = int(os.environ.get("AI_PICK_MAX", "25"))                # 한 번에 판단할 최대 종목 수(PICK + 종합 순위 상위)
AI_PICK_HORIZON = int(os.environ.get("AI_PICK_HORIZON", "20"))        # 🏆 성과 판정: 거래일 안 +30%
EXT_ALERTS = os.environ.get("EXT_ALERTS", "1") != "0"                # 🌙 관심 종목 시간외(프리·애프터·데이마켓) 급등 텔레그램
AI_REVIEW_ENABLED = os.environ.get("AI_REVIEW_ENABLED", "1") != "0"   # 🤖 Claude 복기(주 1회, 놓친 펌핑·실패 신호 원인 분류 · Haiku · 월 예산 안)
CHART_ALERTS = os.environ.get("CHART_ALERTS", "1") != "0"            # 📐 스승 관점(눌림 타점·60분 200선·5분 꺾임·생명선/허리 이탈) 텔레그램 — 보유·저금통 종목(2026-10-27)
CHART_SCAN_MIN = int(os.environ.get("CHART_SCAN_MIN", "10"))         # 📐 스캐너가 5분봉을 받아 보유 종목을 점검하는 주기(분)
EXT_ALERT_PCT = float(os.environ.get("EXT_ALERT_PCT", "10"))           # 직전 정규장 종가 대비 몇 % 이상이면 알릴지
PIGGY_ALERTS = os.environ.get("PIGGY_ALERTS", "1") != "0"            # 🐷 저금통 종목이 저점·고점·이탈 구간에 들어가면 텔레그램 알림(텔레그램 설정 필요)
PIGGY_DAILY_SCAN = os.environ.get("PIGGY_DAILY_SCAN", "1") != "0"    # 매일 아침 갱신 작업(cases.py update)에서 저금통 후보 다시 찾기
INTEL_SEC_MAX_PER_CYCLE = int(os.environ.get("INTEL_SEC_MAX_PER_CYCLE", "60"))       # 공통 인텔: 사이클당 SEC 장중 공시 확인 종목 수(종목당 10분마다)
INTEL_FINTEL_MAX_PER_CYCLE = int(os.environ.get("INTEL_FINTEL_MAX_PER_CYCLE", "20")) # 공통 인텔: 사이클당 Fintel 조회 종목 수(종목당 20분마다)
HALTS_SOURCE = os.environ.get("HALTS_SOURCE", "upcuit").strip().lower()          # "upcuit" | "nasdaq"
CLOSE_WATCH_MAX = int(os.environ.get("CLOSE_WATCH_MAX", "60"))                # 사이클당 추적 종목 수 상한(낙폭이 큰 순)
MAX_CANDIDATES = 100              # 2단계 정밀 분석 대상 상한 (거래량 급증 순)
MAX_NEW_FUNDAMENTALS_PER_CYCLE = 40   # 사이클당 새로 조회할 float/거래소 정보 수
MAX_SEC_CHECKS_PER_CYCLE = 15         # 사이클당 새로 '희석 판정'할 SEC 종목 수 (나머지는 다음 사이클로). 공통 인텔의 장중 공시 확인은 INTEL_SEC_MAX_PER_CYCLE 로 따로 제한


def require_sec_user_agent() -> str:
    if "@" not in SEC_USER_AGENT:
        raise SystemExit(
            "SEC_USER_AGENT 환경변수가 필요합니다. 예) export SEC_USER_AGENT=\"Hong Gildong hong@example.com\"\n"
            "(SEC 규정상 식별 가능한 User-Agent 없이는 요청이 차단될 수 있습니다.)"
        )
    return SEC_USER_AGENT


# ---------------------------------------------------------------- ⚙️ 관리 모드: 대시보드에서 바꾼 설정(DB)이 .env·기본값보다 우선
SETTINGS = {  # 이름: (종류, 최소, 최대, 묶음, 설명)
    "SHORTFLOW_ALERTS": (bool, None, None, "알림", "🩳 공매도 흐름 신호 텔레그램"),
    "FLOWREAD_ALERTS": (bool, None, None, "알림", "📈 분산·털기 신호 텔레그램"),
    "PIGGY_ALERTS": (bool, None, None, "알림", "🐷 저금통 저점·고점·이탈 텔레그램"),
    "EXT_ALERTS": (bool, None, None, "알림", "🌙 관심 종목 시간외 급등 텔레그램"),
    "AI_PICK_ENABLED": (bool, None, None, "알림", "🤖 AI PICK(아침 갱신 때 Claude 판단)"),
    "NEWS_TRANSLATE": (bool, None, None, "알림", "🌐 뉴스 한국어 번역(Haiku · AI 월 예산 안에서)"),
    "SEC_DIGEST": (bool, None, None, "알림", "📝 공시 한국어 요약·병합 일정·13D/13G 추출(Haiku · AI 월 예산 안에서)"),
    "FORENSIC_AI": (bool, None, None, "알림", "🧾 서버 자동 공시분석(덕구 포렌식 · 아침 갱신 때)"),
    "FORENSIC_PER_RUN": (int, 1, 10, "숫자", "🧾 서버 공시분석: 하루에 분석할 종목 수(종목당 약 100~200원)"),
    "FUNDSCAN_AI_PER_DAY": (int, 0, 50, "숫자", "💰 펀드스캔: 규칙으로 행사가를 못 읽은 공시를 Haiku 로 다시 읽는 하루 상한(건당 약 2~5원)"),
    "AI_MONTHLY_BUDGET_KRW": (float, 1000.0, 200000.0, "숫자", "🤖 AI 월 예산(원) — 넘으면 실행하지 않음"),
    "AI_PICK_MAX": (int, 10, 80, "숫자", "🤖 AI PICK 한 번에 판단할 최대 종목 수"),
    "TIER_HOLD_DAYS": (int, 5, 80, "숫자", "⭐ 깊은 과매도+희석 없음: 반등형 보유 기간(거래일, 🏆 성과 판정 기준)"),
    "TIER_TARGET": (float, 5.0, 200.0, "숫자", "⭐ 깊은 과매도+희석 없음: 익절 목표 %"),
    "TIER_STOP": (float, -80.0, -5.0, "숫자", "⭐ 깊은 과매도+희석 없음: 손절 %(음수)"),
    "EXT_ALERT_PCT": (float, 3.0, 100.0, "숫자", "🌙 시간외 급등 알림: 직전 정규장 종가 대비 % 이상"),
    "CHART_ALERTS": (bool, None, None, "알림", "📐 스승 관점 경고·타점(보유·저금통 종목) 텔레그램"),
    "AI_REVIEW_ENABLED": (bool, None, None, "알림", "🤖 Claude 복기(주 1회 · 놓친 펌핑·실패 신호 원인 분류 · Haiku)"),
    "CHART_SCAN_MIN": (int, 3, 60, "숫자", "📐 스캐너 5분봉 점검 주기(분)"),
    "AFTER_ALERTS": (bool, None, None, "알림", "🌙 애프터 진입·매도 마감 텔레그램"),
    "SECFEED_ALERTS": (bool, None, None, "알림", "🔔 워치리스트·저금통 종목 새 공시 텔레그램"),
    "GUEST_ALERTS": (bool, None, None, "알림", "👥 방문객 접속·새 기기·차단 텔레그램"),
    "AFTER_SCALP_ENABLED": (bool, None, None, "기능", "🌙 애프터 스캘핑 판정"),
    "SECFEED_ENABLED": (bool, None, None, "기능", "🔔 SEC 실시간 공시 피드(공시 알림·내부자 매수)"),
    "ACCUM_DAILY": (bool, None, None, "기능", "🧲 매일 아침 매집 의심 분석"),
    "RSPLIT_DAILY": (bool, None, None, "기능", "🔁 매일 아침 분할 기록 갱신"),
    "CLOSE_WATCH_TOP_N": (int, 5, 50, "숫자", "🎯 장마감 체크리스트: 토스 급하락 몇 위까지"),
    "CLOSE_WATCH_MIN_DROP": (float, -60.0, -3.0, "숫자", "🎯 장마감 체크리스트: 최소 낙폭(%)"),
    "AFTER_TOP_N": (int, 10, 60, "숫자", "🌙 애프터: 실시간 거래량 상위 몇 위까지"),
    "SETUP_MAX_PER_CYCLE": (int, 0, 20, "숫자", "🕵️ 세력·셋업: 사이클당 분석 종목 수"),
    "SECFEED_ENRICH_PER_CYCLE": (int, 0, 50, "숫자", "🔔 공시 본문 키워드 판정: 사이클당 건수"),
    "INSIDER_PER_CYCLE": (int, 0, 50, "숫자", "👤 Form 4 원문 읽기: 사이클당 건수"),
    "PRESSURE_REPORTS_PER_DAY": (int, 0, 100, "숫자", "🧭 회사 압박 후보 리포트: 하루 생성 상한"),
    "AI_MONTHLY_BUDGET_KRW": (int, 0, 200000, "숫자", "🤖 AI 요약·교차검증: 월 예산(원)"),
    "PIGGY_AUTO_ADD": (bool, None, None, "기능", "🐷 저금통 자동 담기·빼기(아침 후보 분석 결과로, 카테고리 '🤖 자동')"),
    "PIGGY_AUTO_N": (int, 0, 60, "숫자", "🐷 자동으로 담아 둘 최대 종목 수(안정성 높은 순)"),
    "PIGGY_AUTO_SCORE": (int, 0, 100, "숫자", "🐷 저금통 기준: 안정성 점수 이상"),
    "PIGGY_AUTO_BOUNCES": (int, 0, 6, "숫자", "🐷 저금통 기준: 지지선 반등 횟수 이상"),
    "PIGGY_AUTO_DVOL": (float, 0.0, 10000000.0, "숫자", "🐷 저금통 기준: 20일 평균 거래대금($) 이상"),
    "PIGGY_MAX_KRW": (float, 100.0, 100000.0, "숫자", "🐷 저금통 기준: 주가 이 원화 가격 미만"),
    "PRESIM_ACCOUNT_KRW": (float, 100000.0, 100000000.0, "숫자", "🎲 매매 전 시뮬레이션: 계좌 크기(원) — 수량 상한 10% 의 기준"),
    "PRESIM_MAX_LOSS_KRW": (float, 1000.0, 1000000.0, "숫자", "🎲 한 번 매매의 최대 손실(원) — 수량 = 이것 ÷ (매수가 − 손절가)"),
    "PRESIM_TOP_N": (int, 0, 50, "숫자", "🎲 아침 자동 실행: 종합 순위 상위 몇 개까지(0 = 순위는 안 돌림)"),
    "PRESIM_REGIME_VERDICT": (bool, None, None, "기능", "🎲 대표 판정에 장세 반영(켜면 '2년 전체'와 '오늘과 같은 장세 날만' 중 더 조심스러운 판정을 배지·목록에 씀)"),
    "RANK_W_STRENGTH": (float, 0.3, 1.0, "순위 가중치", "🏁 종합 = 강도 × 이 값 + 임박도 × (1 − 이 값)"),
    "RANK_W_ACC": (float, 0.0, 1.0, "순위 가중치", "강도: 매집 비중"),
    "RANK_W_PR": (float, 0.0, 1.0, "순위 가중치", "강도: 회사 압박 비중"),
    "RANK_W_SQ": (float, 0.0, 1.0, "순위 가중치", "강도: 스퀴즈 비중"),
    "RANK_W_MS": (float, 0.0, 1.0, "순위 가중치", "강도: 멀티 시그널 비중"),
    "RANK_W_NEWS": (float, 0.0, 1.0, "순위 가중치", "강도: 공시 호재 비중"),
    "RANK_W_INS": (float, 0.0, 1.0, "순위 가중치", "강도: 내부자 매수 비중"),
    # 💵 실매매(4단계 1주 모드, 2026-10-29 — broker.py). 기본 전부 꺼짐·1주. 설계: docs/broker_design_2026-10.md
    "LIVE_TRADING": (bool, None, None, "실매매", "💵 실주문 스위치(끄면 dry-run: 기록만). 관리 모드에서 두 단계 확인 뒤 켬"),
    "LIVE_ONE_SHARE": (bool, None, None, "실매매", "1주 모드: 금액과 상관없이 종목당 1주만(11월 말 결정 뒤 끄면 아래 금액 적용)"),
    "LIVE_STRATEGIES": (str, None, None, "실매매", "실주문을 내는 가상매매 전략(쉼표로): piggy · rank · pick · master · close · after"),
    "LIVE_USD_PER_TRADE": (float, 10.0, 500.0, "실매매", "1주 모드가 꺼졌을 때 종목당 매수 금액($)"),
    "LIVE_MAX_ORDERS_PER_DAY": (int, 1, 10, "실매매", "하루 매수 주문 상한(어뷰징 방지)"),
    "LIVE_MAX_OPEN": (int, 1, 10, "실매매", "동시 보유 종목 상한"),
    "LIVE_MAX_EXPOSURE_USD": (float, 50.0, 5000.0, "실매매", "보유 평가액 + 미체결 매수 합계 상한($)"),
    "LIVE_MAX_PRICE": (float, 0.5, 50.0, "실매매", "이 주가($) 넘는 종목은 안 삼"),
    "LIVE_MIN_DOLLAR_VOL": (float, 0.0, 10000000.0, "실매매", "20일 평균 거래대금($) 미만이면 안 삼"),
    "LIVE_LIMIT_SLIP_PCT": (float, 0.2, 3.0, "실매매", "지정가 여유폭(%): 매수 +, 매도 −"),
    "LIVE_ORDER_TTL_MIN": (int, 5, 240, "실매매", "미체결 매수를 취소하기까지(분). 그날 재시도 안 함"),
    "LIVE_DAILY_LOSS_USD": (float, 5.0, 1000.0, "실매매", "오늘 실현손실이 이 금액($)을 넘으면 킬 스위치"),
    "LIVE_ACCOUNT_SEQ": (str, None, None, "실매매", "주문 계좌 accountSeq(비우면 첫 종합매매 계좌)"),
    "LIVE_SYNC_SEC": (int, 20, 600, "실매매", "체결·요청 동기화 주기(초) — 스캐너 주기(정규장 ≈13분)와 별도의 배경 스레드"),
    "LIVE_EXT_SESSIONS": (bool, None, None, "실매매", "시간외(프리·애프터·데이마켓)에도 주문 — 시간외 1주 테스트로 확인한 뒤에만 켤 것(장마감·애프터 전략용)"),
    "RANK_NEWS_EVIDENCE": (bool, None, None, "순위 가중치", "🧮 공시 점수를 과거 성과(이벤트 연구) 기준으로 — 검증 통과 때만, 끄면 예전 호재/악재 규칙"),
    "AI_AUTO_CHECK": (bool, None, None, "기능", "🔀 새 덕구 보고서가 들어오면 자동 교차검증"),
    "AI_MODEL": (str, None, None, "AI", "🤖 AI 모델(Opus 는 더 정확하지만 비용 약 2배)"),
}
PT_TOP_N, PT_TP, PT_SL, PT_HOLD, PT_USD = 3, 20.0, 10.0, 3, 1000.0          # 🧪 가상매매 '종합 순위' 전략 기본값(전략별 설정은 papertrade.settings · 관리 모드)
PIGGY_AUTO_ADD, PIGGY_AUTO_N, PIGGY_AUTO_SCORE, PIGGY_AUTO_BOUNCES, PIGGY_AUTO_DVOL, PIGGY_MAX_KRW = True, 20, 60, 2, 20000.0, 1000.0   # 🐷 저금통 자동 담기 기준(2026-10-27)
RANK_W_STRENGTH, RANK_W_ACC, RANK_W_PR, RANK_W_SQ, RANK_W_MS, RANK_W_NEWS, RANK_W_INS = 0.7, 0.25, 0.20, 0.20, 0.15, 0.10, 0.10   # 🏁 순위 가중치
RANK_NEWS_EVIDENCE = True   # 🧮 공시 점수 = 과거 성과 기반(evscore, 검증 통과 때만)
# 💵 실매매 기본값(전부 안전한 쪽): 꺼짐 · 1주 모드 · 저금통만 · 하루 3건 · 3종목/$500 · $5 이하 · 거래대금 $50k · 여유 1% · 30분 TTL · 일손실 $50
LIVE_TRADING, LIVE_ONE_SHARE, LIVE_STRATEGIES, LIVE_USD_PER_TRADE = False, True, "piggy", 100.0
LIVE_MAX_ORDERS_PER_DAY, LIVE_MAX_OPEN, LIVE_MAX_EXPOSURE_USD, LIVE_MAX_PRICE, LIVE_MIN_DOLLAR_VOL = 3, 3, 500.0, 5.0, 50000.0
LIVE_LIMIT_SLIP_PCT, LIVE_ORDER_TTL_MIN, LIVE_DAILY_LOSS_USD, LIVE_ACCOUNT_SEQ, LIVE_SYNC_SEC, LIVE_EXT_SESSIONS = 1.0, 30, 50.0, "", 60, False
GUEST_ALERTS = os.environ.get("GUEST_ALERTS", "1") != "0"                      # 👥 방문객 접속 알림
AI_MONTHLY_BUDGET_KRW = int(os.environ.get("AI_MONTHLY_BUDGET_KRW", "10000"))   # 🤖 AI 월 예산(원)
AI_AUTO_CHECK = os.environ.get("AI_AUTO_CHECK", "1") != "0"                     # 🔀 새 덕구 보고서 자동 교차검증
AI_MODEL = os.environ.get("AI_MODEL", "claude-sonnet-5-5")                        # 🤖 claude-sonnet-5-5 / claude-opus-5-5
AI_MODELS = ["claude-sonnet-5-5", "claude-opus-5-5"]
_DEFAULTS = {k: globals().get(k) for k in SETTINGS}


def _cast(name: str, v):
    kind, lo, hi = SETTINGS[name][:3]
    if kind is bool:
        return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on", "yes")
    if kind is str:
        return str(v)
    v = kind(v)
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def overrides() -> dict:
    try:
        import json
        import db
        m = db.get_meta("settings")
        return json.loads(m["value"]) if m and m.get("value") else {}
    except Exception:  # noqa: BLE001
        return {}


def apply_overrides() -> dict:
    """DB 에 저장된 관리 모드 설정을 이 모듈 값에 반영(없으면 .env·기본값 그대로). 반영한 설정을 돌려준다."""
    ov = overrides()
    for k in SETTINGS:
        globals()[k] = _cast(k, ov[k]) if k in ov else _DEFAULTS[k]
    return {k: v for k, v in ov.items() if k in SETTINGS}


def save_overrides(values: dict) -> None:
    import json
    import db
    clean = {k: _cast(k, v) for k, v in values.items() if k in SETTINGS}
    db.set_meta("settings", json.dumps(clean, ensure_ascii=False))
    apply_overrides()
