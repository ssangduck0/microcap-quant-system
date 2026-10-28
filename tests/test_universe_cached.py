"""universe.cached_tickers(2026-10-28): 상장 종목 캐시 파일을 네트워크 없이 읽음(토스 목록 우선 · 없으면 나스닥 파일 · 깨진 파일은 건너뜀 · 둘 다 없으면 [])."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from pathlib import Path
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db")
sys.path.insert(0, os.environ["QS_ROOT"])
import config, universe
config.SCAN_UNIVERSE = "nasdaq"
universe._cache_path = lambda key: Path(tmp) / ("universe_cache_" + key.replace(":", "_") + ".json")   # 프로젝트 폴더 파일을 건드리지 않게 임시 폴더로
assert universe.cached_tickers() == []                                                                 # 파일 없음
(Path(tmp) / "universe_cache_nasdaq.json").write_text(json.dumps({"ts": 0, "tickers": ["BBB", "AAA", "AAA"]}), encoding="utf-8")
assert universe.cached_tickers() == ["AAA", "BBB"]                                                     # 나스닥 파일(오래된 ts 라도 그대로)
(Path(tmp) / "universe_cache_toss_nasdaq.json").write_text("{broken", encoding="utf-8")
assert universe.cached_tickers() == ["AAA", "BBB"]                                                     # 깨진 토스 파일은 건너뜀
(Path(tmp) / "universe_cache_toss_nasdaq.json").write_text(json.dumps({"ts": 0, "tickers": ["ZZZ", "YYY"]}), encoding="utf-8")
assert universe.cached_tickers() == ["YYY", "ZZZ"]                                                     # 토스 목록 우선
config.SCAN_UNIVERSE = "weird"; assert universe.cached_tickers() == ["YYY", "ZZZ"]                     # 모르는 모드는 nasdaq 으로
print("ALL OK")
