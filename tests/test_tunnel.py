import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, tunnel
tunnel.check_reach = False
db.init_db()
os.environ.pop("DASH_PASSWORD", None); assert tunnel.password_ok()[0] is False
os.environ["DASH_PASSWORD"] = "short"; assert tunnel.password_ok()[0] is False and "8자" in tunnel.password_ok()[1]
os.environ["DASH_PASSWORD"] = "longenough1"; assert tunnel.password_ok() == (True, "")
sent = []
lines = ["2026-10-16T12:00:00Z INF Requesting new quick Tunnel on trycloudflare.com...",
         "2026-10-16T12:00:01Z INF |  https://abc-def-123.trycloudflare.com                                                  |",
         "2026-10-16T12:00:02Z INF Registered tunnel connection", "https://abc-def-123.trycloudflare.com again"]
assert tunnel.watch_lines(lines, send=lambda m: sent.append(m) or True) == "https://abc-def-123.trycloudflare.com"
assert len(sent) == 1 and "abc-def-123.trycloudflare.com" in sent[0] and db.get_meta("tunnel_url")["value"] == "https://abc-def-123.trycloudflare.com"
assert open(os.path.join(tmp, "tunnel_url.txt")).read().strip() == "https://abc-def-123.trycloudflare.com"
tunnel.watch_lines(["https://abc-def-123.trycloudflare.com"], send=lambda m: sent.append(m) or True); assert len(sent) == 1     # 같은 주소면 다시 안 보냄
tunnel.watch_lines(["https://new-one-9.trycloudflare.com"], send=lambda m: sent.append(m) or True); assert len(sent) == 2      # 바뀌면 보냄
assert tunnel.watch_lines(["nothing here"], send=lambda m: sent.append(m)) is None
os.environ.pop("DASH_PASSWORD")
assert tunnel.run_forever() == 2                                                                                                 # 비밀번호 없으면 켜지 않음
print("ALL OK")
