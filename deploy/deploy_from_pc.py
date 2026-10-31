"""🚀 PC → 서버 한 줄 배포 (Claude Code 나 cmd 에서):  python deploy/deploy_from_pc.py
1) 프로젝트 폴더를 zip 으로 묶음(.env · .git · venv · __pycache__ · *.db · 큰 데이터는 빼고)
2) 서버로 scp → 3) 서버에서 풀어 /home/quant/quant_system 에 덮어쓰기 · 소유자 정리 · 서비스 재시작
4) 서비스 상태를 보여 줌(모두 active 여야 정상)
· 서버의 .env 와 DB(/home/quant/data) 는 건드리지 않음
· SSH 키 암호를 매번 묻지 않게 하려면 ssh-agent 에 키를 올려 두세요(README · CLAUDE.md 참고)
· --dry-run : 묶기만 하고 보내지 않음 · --no-restart : 올리기만
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SERVER = os.environ.get("QS_SERVER", "root@158.247.250.15")
ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", "node_modules", ".claude", "data", "forensic"}
SKIP_EXT = {".db", ".db-wal", ".db-shm", ".zip", ".log", ".pyc"}
SKIP_NAMES = {".env", "env.txt"}
REMOTE = ("cd /root && rm -rf /root/new && python3 -m zipfile -e qs.zip /root/new && "
          "cp -a /root/new/quant_system/. /home/quant/quant_system/ && rm -rf /root/new && "
          "chown -R quant:quant /home/quant/quant_system")


def build_zip(dest: Path) -> int:
    n = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, files in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for f in files:
                p = Path(dirpath) / f
                if f in SKIP_NAMES or p.suffix.lower() in SKIP_EXT:
                    continue
                arc = Path("quant_system") / p.relative_to(ROOT)
                z.write(p, arc.as_posix())
                n += 1
    return n


def run(cmd: list[str]) -> int:
    print("$", " ".join(cmd))
    return subprocess.call(cmd)


def main() -> int:
    dry = "--dry-run" in sys.argv
    restart = "--no-restart" not in sys.argv
    tmp = Path(tempfile.gettempdir()) / "qs_deploy.zip"
    n = build_zip(tmp)
    print(f"📦 {n}개 파일 → {tmp} ({tmp.stat().st_size / 1e6:.1f} MB)")
    if dry:
        return 0
    if run(["scp", str(tmp), f"{SERVER}:/root/qs.zip"]) != 0:
        print("❌ 올리기 실패 — SSH 키·서버 주소를 확인하세요")
        return 1
    remote = REMOTE + (" && systemctl restart 'quant-*' && (systemctl start --no-block quant-warm.service 2>/dev/null || true)"
                       " && sleep 5 && systemctl list-units 'quant-*' --no-pager --plain | head -16" if restart else "")   # 🔥 재시작 직후 화면 캐시 한 번 데움
    if run(["ssh", SERVER, remote]) != 0:
        print("❌ 서버 적용 실패")
        return 1
    _record_deploy(n)
    print("✅ 배포 완료 — 위 목록이 모두 active 면 정상이에요")
    return 0


def _record_deploy(n: int) -> None:
    """🛠 운영 현황 📜 작업 기록에 배포 한 줄(2026-10-31) — 실패해도 배포는 성공으로 둠."""
    try:
        head = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h %s"], capture_output=True, text=True, encoding="utf-8").stdout.strip()
    except Exception:  # noqa: BLE001
        head = ""
    msg = f"배포 · 파일 {n}개" + (f" · 커밋 {head[:80]}" if head else "")
    b64 = base64.b64encode(msg.encode("utf-8")).decode()
    code = f"import base64,datetime as d,jobs;jobs.record('deploy',d.datetime.now(d.timezone.utc),summary=base64.b64decode('{b64}').decode('utf-8'))"
    subprocess.call(["ssh", SERVER, f"cd /home/quant/quant_system && sudo -u quant venv/bin/python -c \"{code}\""])


if __name__ == "__main__":
    sys.exit(main())
