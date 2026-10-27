import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import importlib, os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db")
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
for k in ("DASH_TUNNEL_NAME", "DASH_PUBLIC_URL", "GUEST_TUNNEL_NAME", "GUEST_PUBLIC_URL", "TUNNEL_KIND"):
    os.environ.pop(k, None)
import db, tunnel
db.init_db()
tunnel.check_reach = False

# 설정이 없으면 지금처럼 임시 터널(주소 매번 바뀜)
assert tunnel.fixed() == ("", "")
assert tunnel.command("cf") == ["cf", "tunnel", "--no-autoupdate", "--url", "http://localhost:8501"]

# 고정 주소 모드
os.environ["DASH_TUNNEL_NAME"] = "quant-dash"; os.environ["DASH_PUBLIC_URL"] = "https://dash.example.com/"
assert tunnel.fixed() == ("quant-dash", "https://dash.example.com")
assert tunnel.command("cf") == ["cf", "tunnel", "--no-autoupdate", "run", "--url", "http://localhost:8501", "quant-dash"]
msgs = []
assert tunnel.on_url("https://dash.example.com", send=lambda m: msgs.append(m) or True) is True
assert db.get_meta("tunnel_url")["value"] == "https://dash.example.com" and "고정" in msgs[0] and "홈 화면" in msgs[0]
assert tunnel.on_url("https://dash.example.com", send=lambda m: msgs.append(m) or True) is False and len(msgs) == 1   # 같은 주소면 조용히
os.environ["DASH_PUBLIC_URL"] = "http://dash.example.com"
assert tunnel.fixed() == ("", "")                                                         # https 가 아니면 켜지 않음

# 방문객 쪽(TUNNEL_KIND=guest, 8502)
os.environ["TUNNEL_KIND"] = "guest"; os.environ["DASH_PORT"] = "8502"
os.environ["GUEST_TUNNEL_NAME"] = "quant-guest"; os.environ["GUEST_PUBLIC_URL"] = "https://guest.example.com"
g = importlib.reload(tunnel)
assert g.KEY == "guest_tunnel_url" and g.fixed() == ("quant-guest", "https://guest.example.com")
assert g.command("cf")[-3:] == ["--url", "http://localhost:8502", "quant-guest"]
print("ALL OK")
