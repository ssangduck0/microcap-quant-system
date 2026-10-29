"""filelog — 프로그램 로그를 DB 폴더 파일에도: 붙이기(중복 없음) · 진행 줄 INFO · 경고만 고르기(최근 n일) · 꼬리."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile, logging
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db")
sys.path.insert(0, os.environ["QS_ROOT"])
from datetime import datetime, timedelta
import filelog

logging.basicConfig(level=logging.WARNING, format=filelog.FMT)
p = filelog.attach("cases", level=logging.INFO); assert p is not None and p.name == "cases.log" and p.parent == __import__("pathlib").Path(tmp)
assert filelog.attach("cases", level=logging.INFO) == p and sum(1 for h in logging.getLogger().handlers if getattr(h, "baseFilename", "") == str(p)) == 1   # 두 번 붙여도 하나
out = filelog.out_logger("cases.out").info
out("공시 이력 동기화: 피드에서 3건 추가")
logging.getLogger("cases").warning("공매도 잔고 갱신 실패: 테스트")
logging.getLogger("other").error("부검 실패: 테스트")
logging.getLogger("cases").info("루트가 WARNING 이라 이 줄은 안 남음")
for h in logging.getLogger().handlers:
    h.flush()
txt = p.read_text(encoding="utf-8")
assert "공시 이력 동기화: 피드에서 3건 추가" in txt and "공매도 잔고 갱신 실패" in txt and "부검 실패" in txt and "이 줄은 안 남음" not in txt, txt
w = filelog.warnings("cases", days=7); assert len(w) == 2 and all(("WARNING" in x or "ERROR" in x) for x in w) and "동기화" not in "\n".join(w), w
# 오래된 줄은 빠진다
old = (datetime.now() - timedelta(days=9)).strftime("%Y-%m-%d") + " 07:30:00,000 WARNING cases: 옛날 실패\n"
p.write_text(old + txt, encoding="utf-8")
assert len(filelog.warnings("cases", days=7)) == 2 and len(filelog.warnings("cases", days=30)) == 3
t = filelog.tail("cases", 2); assert t and len(t) == 2 and "부검 실패" in t[-1]
assert filelog.tail("nothing") is None and filelog.warnings("nothing") == []
print("ALL OK")
