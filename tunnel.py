"""📱 휴대폰으로 보기 — Cloudflare 임시 터널(무료·계정 불필요)로 대시보드를 https 주소로 열고, 주소를 텔레그램으로 보낸다.

python tunnel.py          터널을 켜고(끊기면 30초 뒤 다시) 새 주소가 나올 때마다 텔레그램 전송 + DB 저장
start_tunnel.bat          위를 자동 재시작으로 실행(로그: C:\\quant_data\\tunnel.log)
준비: cloudflared 설치 — 명령 프롬프트에서  winget install --id Cloudflare.cloudflared
안전: 인터넷에 열리는 주소라 .env 의 DASH_PASSWORD(8자 이상)가 없으면 켜지 않는다. 주소는 터널을 다시 켤 때마다 바뀐다.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import config
import db

log = logging.getLogger("tunnel")
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
CANDIDATES = [Path(config.BASE_DIR) / "cloudflared.exe", Path(r"C:\quant_data\cloudflared.exe"),
              Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe"), Path(r"C:\Program Files\cloudflared\cloudflared.exe")]
PORT = int(os.environ.get("DASH_PORT", "8501"))
GUEST = os.environ.get("TUNNEL_KIND") == "guest"  # 방문객 전용 서버(8502)용 터널
KEY = "guest_tunnel_url" if GUEST else "tunnel_url"
LABEL = "👥 방문객 전용 주소" if GUEST else "📱 대시보드 휴대폰 주소"


def fixed() -> tuple[str, str]:
    """🔒 고정 주소 모드: (이름 있는 터널 이름, 공개 주소). .env 의 DASH_/GUEST_TUNNEL_NAME · DASH_/GUEST_PUBLIC_URL — 둘 다 있어야 켜짐."""
    pre = "GUEST_" if GUEST else "DASH_"
    name = os.environ.get(pre + "TUNNEL_NAME", "").strip()
    url = os.environ.get(pre + "PUBLIC_URL", "").strip().rstrip("/")
    return (name, url) if name and url.startswith("https://") else ("", "")


def command(exe: str) -> list[str]:
    """cloudflared 실행 명령 — 고정 주소 모드면 이름 있는 터널, 아니면 임시 터널(주소가 매번 바뀜)."""
    name, _ = fixed()
    if name:
        return [exe, "tunnel", "--no-autoupdate", "run", "--url", f"http://localhost:{PORT}", name]
    return [exe, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{PORT}"]


def find_cloudflared() -> str | None:
    p = shutil.which("cloudflared")
    if p:
        return p
    for c in CANDIDATES:
        if c.exists():
            return str(c)
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if local.exists():
        for exe in local.glob("Cloudflare.cloudflared*/**/cloudflared*.exe"):
            return str(exe)
    return None


def password_ok() -> tuple[bool, str]:
    pw = os.environ.get("DASH_PASSWORD", "").strip()
    if not pw:
        return False, ".env 에 DASH_PASSWORD 가 없습니다. 인터넷에 열리는 주소라 비밀번호 없이 켜지 않습니다."
    if len(pw) < 8:
        return False, "DASH_PASSWORD 가 너무 짧습니다(8자 이상)."
    return True, ""


def reachable(url: str, wait: float = 20.0, get=None) -> tuple[bool, str]:
    """새 주소가 실제로 열리는지(터널이 바로 연결되지 않을 수 있어 몇 번 다시 시도)."""
    import requests
    get = get or (lambda u: requests.get(u, timeout=10))
    deadline, last = time.time() + wait, ""
    while True:
        try:
            r = get(url)
            if r.status_code < 500:
                return True, f"HTTP {r.status_code}"
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = type(e).__name__
        if time.time() >= deadline:
            return False, last
        time.sleep(3)


def check() -> int:
    """휴대폰 주소 점검: 비밀번호 · cloudflared · 대시보드(localhost) · 마지막 주소가 열리는지."""
    import requests
    db.init_db()
    ok, why = password_ok()
    print(("✅" if ok else "❌") + " 비밀번호(DASH_PASSWORD): " + ("설정됨" if ok else why))
    exe = find_cloudflared()
    print(("✅" if exe else "❌") + " cloudflared: " + (exe or "못 찾음 — winget install --id Cloudflare.cloudflared 후 창을 새로 열기"))
    try:
        r = requests.get(f"http://localhost:{PORT}", timeout=5)
        print(f"✅ 대시보드 localhost:{PORT} 응답 HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        print(f"❌ 대시보드 localhost:{PORT} 응답 없음({type(e).__name__}) — start_dashboard.bat 가 켜져 있는지 확인")
    for key, label in (("tunnel_url", "내 휴대폰 주소"), ("guest_tunnel_url", "방문객 전용 주소")):
        url = (db.get_meta(key) or {}).get("value") or ""
        seen = (db.get_meta(key + "_seen") or {}).get("value") or "-"
        if not url:
            print(f"❌ {label} 없음 — " + ("start_tunnel.bat" if key == "tunnel_url" else "start_guest_dashboard.bat · start_guest_tunnel.bat") + " 가 켜져 있는지 확인")
        else:
            good, msg = reachable(url, wait=10)
            print(("✅" if good else "❌") + f" {label} {url} ({seen}) → {msg}")
    import config as _c
    print(("✅" if _c.TELEGRAM_TOKEN and _c.TELEGRAM_CHAT_ID else "❌") + " 텔레그램 설정(TELEGRAM_TOKEN·TELEGRAM_CHAT_ID)")
    return 0


check_reach = True  # 테스트에서 끔


def on_url(url: str, send=None) -> bool:
    """새 주소면 저장하고 텔레그램 전송. 같은 주소면 아무것도 안 함. 새 주소였으면 True."""
    old = (db.get_meta(KEY) or {}).get("value")
    db.set_meta(KEY, url)
    db.set_meta(KEY + "_seen", db.utcnow_iso())
    try:
        Path(config.DB_PATH).with_name(("guest_" if GUEST else "") + "tunnel_url.txt").write_text(url + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    if url == old:
        return False
    if send is None:
        import notify
        send = notify.send_telegram
    good, msg = reachable(url) if check_reach else (True, "점검 생략")
    log.info("새 주소 점검: %s %s", url, msg)
    note = "방문객 링크는 이 주소로 다시 만들어 보내세요(관리 모드). " if GUEST else "비밀번호는 .env 의 DASH_PASSWORD 입니다. "
    if fixed()[0]:
        note += "🔒 고정 주소라 다시 바뀌지 않아요 — 휴대폰 홈 화면에 추가해 두세요."
        ok = send(f"{LABEL}(고정)\n{url}\n{note}")
        log.info("고정 주소 %s · 텔레그램 %s", url, "전송" if ok else "실패/미설정")
        return True
    warn = "" if good else f" ⚠️ PC 에서 열어 보니 아직 응답이 없어요({msg}) — 1~2분 뒤 다시 열어 보세요"
    ok = send(f"{LABEL}(새로 바뀜){warn}\n{url}\n{note}터널을 다시 켜면 주소가 바뀝니다.")
    log.info("새 주소 %s · 텔레그램 %s", url, "전송" if ok else "실패/미설정")
    return True


def watch_lines(lines, send=None) -> str | None:
    """cloudflared 출력 줄들에서 주소를 찾으면 처리. 찾은 마지막 주소를 돌려준다."""
    found = None
    for line in lines:
        m = URL_RE.search(line if isinstance(line, str) else line.decode("utf-8", "replace"))
        if m and m.group(0) != found:
            found = m.group(0)
            on_url(found, send)
    return found


def run_forever() -> int:
    ok, why = password_ok()
    if not ok:
        print("❌", why)
        return 2
    exe = find_cloudflared()
    if not exe:
        print("❌ cloudflared 를 찾지 못했습니다. 명령 프롬프트에서:  winget install --id Cloudflare.cloudflared  (설치 후 창을 새로 여세요)")
        return 2
    db.init_db()
    name, furl = fixed()
    if not name:
        db.set_meta(KEY, "")  # 다시 켜면 주소가 바뀌므로 예전 주소는 바로 지움(죽은 주소로 링크가 만들어지지 않게)
    while True:
        log.info("터널 시작: %s → http://localhost:%d%s", exe, PORT, f" · 고정 주소 {furl}(터널 {name})" if name else "")
        try:
            p = subprocess.Popen(command(exe), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            if name:
                on_url(furl)  # 고정 주소는 바뀌지 않음 — 처음 한 번만 텔레그램(같은 주소면 조용히)
                for line in p.stdout:
                    if " ERR " in line and "ICMP" not in line:  # 실제 오류만(ICMP 프록시 경고 등 무해한 WRN 은 남기지 않음)
                        log.warning("cloudflared: %s", line.strip()[:200])
            else:
                watch_lines(p.stdout)
            p.wait()
        except Exception as e:  # noqa: BLE001
            log.warning("터널 오류: %s", e)
        if not name:
            db.set_meta(KEY, "")
        log.info("터널이 끊겼습니다. 30초 뒤 다시 켭니다.")
        time.sleep(30)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(check() if len(sys.argv) > 1 and sys.argv[1] == "check" else run_forever())
