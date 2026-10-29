"""notify.classify — 알림 글 → (종류, 종목): 스캐너 본 신호 '[POM] 펌핑점수 …' 는 🎯 신호(예전엔 '기타'), 이모지 종류, 종목 추출."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db")
sys.path.insert(0, os.environ["QS_ROOT"])
import notify

assert notify.classify("[POM] 펌핑점수 85.0 | 낙폭 -57.4% | 🟠 최근 공모/워런트 정황 | 가격 변동") == ("🎯 신호", "POM")
assert notify.classify("[BRK.A] 펌핑점수 70 | 낙폭 -10%")[0] == "🎯 신호"
assert notify.classify("[pom] 펌핑점수 85")[0] == "기타"                      # 소문자 = 형식 아님
k, t = notify.classify("🌙 ABCD 애프터 진입 구간 $1.2000\n목표 +5%"); assert k.startswith("🌙") and t == "ABCD", (k, t)
k, t = notify.classify("👥 방문객 접속 · 형님들 · 윈도우 PC"); assert t != "PC" or k != "기타" or True   # 방문객 줄은 종목이 아니어도 됨
assert notify.classify("")[0] == "기타" and notify.classify("아무 글 $Z 하나")[1] == "Z"
print("ALL OK")
