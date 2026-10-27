import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import sys; sys.path.insert(0, __import__("os").environ["QS_ROOT"])
import regsho, requests
calls = []
class R:
    def __init__(s, c, t): s.status_code, s.text = c, t
def fake(url, headers=None, timeout=None):
    calls.append(headers["User-Agent"])
    return R(200, "Symbol|Security Name|Market Category|Reg SHO Threshold Flag|Rule 3210|Filler\nAAPD|X|G|Y|N|\n") if headers["User-Agent"] == "Mozilla/5.0" else R(200, "<html>blocked</html>")
requests.get = fake
code, text = regsho.fetch("u"); assert code == 200 and regsho.parse(text) == {"AAPD": "X"} and calls == ["Mozilla/5.0"]
calls.clear()
def fake2(url, headers=None, timeout=None):
    calls.append(headers["User-Agent"])
    return R(200, "<html>blocked</html>") if headers["User-Agent"] == "Mozilla/5.0" else R(200, "Symbol|Security Name|x\nBBB|Y|G|Y|N|\n")
requests.get = fake2
code, text = regsho.fetch("u"); assert regsho.parse(text) == {"BBB": "Y"} and len(calls) == 2      # 짧은 이름표가 막히면 크롬 이름표로
calls.clear(); requests.get = lambda url, headers=None, timeout=None: (calls.append(1), R(404, ""))[1]
assert regsho.fetch("u") == (404, "") and len(calls) == 1                                          # 404 는 한 번만
print("ALL OK")
