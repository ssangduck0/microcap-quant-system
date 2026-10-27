# 🖥 서버 이전 안내 — Vultr 서울 (집 PC → 24시간 서버)

PC를 꺼도 스캐너·대시보드·아침 갱신이 계속 돌게 합니다. **한 번에 다 옮기지 않고**, 서버에서 **접속 시험**을 통과한 뒤 옮깁니다.
비용: 2 vCPU / 4 GB 약 **월 $20**(시간 단위 요금 — 결제 직전에 공식 화면에서 다시 확인).

---
## 0. 준비 (집 PC)
1. **텔레그램 토큰 재발급**(꼭): 텔레그램 @BotFather → `/mybots` → 봇 선택 → API Token → **Revoke current token** → 새 토큰을 `.env` 의 `TELEGRAM_TOKEN=` 에 붙여넣기.
2. 최신 zip 을 PC 에 적용해 둡니다(평소처럼).

## 1. Vultr 계정
1. vultr.com → **Sign Up** → 이메일 인증
2. **Billing** 에서 카드(또는 PayPal) 등록
3. **2단계 인증 켜기**: 오른쪽 위 계정 → **Authentication** → **Two Factor** → 휴대폰 인증 앱(Google Authenticator 등)으로 등록

## 2. SSH 키 만들기 (집 PC cmd 창)
비밀번호 대신 **열쇠 파일**로 서버에 들어가게 합니다(가장 흔한 해킹인 비밀번호 맞히기를 막음).
```
ssh-keygen -t ed25519 -C quant-server
```
- 저장 위치를 물으면 **Enter**(기본 위치)
- passphrase(열쇠 암호)를 물으면 **기억할 수 있는 암호** 입력(권장)

공개 키 보기:
```
type %USERPROFILE%\.ssh\id_ed25519.pub
```
나온 한 줄(`ssh-ed25519 ...`)을 복사 → Vultr 계정 메뉴 **SSH Keys** → **Add SSH Key** → 이름 `quant-pc` → 붙여넣기 → 저장.
⚠️ `id_ed25519`(.pub 없는 파일)는 **진짜 열쇠**라 절대 남에게 보내지 마세요.

## 3. 서버 만들기
**Deploy +** → 아래처럼 고릅니다(화면 이름은 조금 다를 수 있어요).

| 항목 | 선택 |
|---|---|
| 종류 | **Cloud Compute – Shared CPU** |
| 위치 | **Seoul** |
| 이미지 | **Ubuntu 24.04 LTS x64** |
| 요금제 | **Regular Performance · 2 vCPU · 4 GB** (약 $20/월) |
| SSH Keys | **quant-pc 체크** |
| 자동 백업 | 선택(월 +20%). 서버가 매일 DB 를 따로 백업하고, 2026-10-28 부터 Cloudflare R2 에도 사본을 두므로 꼭 필요하진 않음 |
| Hostname | `quant` |

**Deploy Now** → 1~2분 뒤 **Running** → 서버의 **IP 주소**를 메모합니다.

## 4. 파일 올리기 (집 PC cmd 창)
경로에 한글이 있어 그대로 올리면 꼬일 수 있어서, 영문 경로로 복사해서 올립니다. `서버IP` 를 바꿔 넣으세요.
```
copy "C:\Users\admin\OneDrive\바탕 화면\덕\공부\클로드\files\quant_system.zip" C:\quant_data\qs.zip
copy "C:\Users\admin\OneDrive\바탕 화면\덕\공부\클로드\files\quant_system\quant_system\.env" C:\quant_data\env.txt
scp C:\quant_data\qs.zip C:\quant_data\env.txt root@서버IP:/root/
del C:\quant_data\env.txt
```
처음 접속할 때 `yes` → (passphrase 를 정했다면) 열쇠 암호 입력.

## 5. 설치 (서버)
```
ssh root@서버IP
cd /root && python3 -m zipfile -e qs.zip /root/ && mv env.txt quant_system/.env
cd /root/quant_system && bash deploy/setup_server.sh
```
5~10분 걸립니다(방화벽·자동 보안 업데이트·fail2ban 까지 설정).

## 6. 접속 시험 ← 가장 중요
```
sudo -u quant /home/quant/quant_system/venv/bin/python /home/quant/quant_system/deploy/check_connectivity.py
```
- **야후 일봉·5분봉**이 ✅ 여야 합니다. ❌ 면 서버를 지우고(Destroy) 다시 만들면 IP 가 바뀝니다. 그래도 ❌ 면 도쿄(Tokyo)로.
- **토스**가 403 이면: 토스증권 WTS(PC 웹) → 설정 → Open API → **허용 IP** 에 결과 맨 위의 **서버 공인 IP** 추가 → 다시 시험.
- **결과를 Claude 에게 붙여 주세요.** 통과하면 7단계로.

## 7. 비밀번호 로그인 끄기 (서버)
SSH 키로 들어와 있는 상태에서:
```
bash /root/quant_system/deploy/harden_ssh.sh
```
그다음 **지금 창은 닫지 말고** 새 cmd 창에서 `ssh root@서버IP` 가 되는지 확인합니다. 안 되면 Vultr 서버 화면의 **View Console**(웹 콘솔)로 들어가 `/etc/ssh/sshd_config.d/00-quant-hardening.conf` 를 지우면 원래대로 돌아갑니다.

## 8. 전환 (시험 통과 후)
**집 PC** (cmd 창):
```
cd /d "C:\Users\admin\OneDrive\바탕 화면\덕\공부\클로드\files\quant_system\quant_system"
uninstall_autostart.bat
taskkill /F /IM python.exe
scp C:\quant_data\quant.db root@서버IP:/home/quant/data/quant.db
```
**작업 스케줄러**(시작 메뉴에서 검색) → 아침 갱신(`run_cases_update.bat`) 작업 → **사용 안 함**(두 곳에서 같이 돌지 않게).
토스는 **한 곳에서만** 쓰세요 — 전환 후 PC 에서 스캐너를 다시 켜지 마세요.

**서버**:
```
chown quant:quant /home/quant/data/quant.db
systemctl enable --now quant-scanner quant-dashboard quant-guest quant-tunnel quant-guest-tunnel quant-collector quant-cases.timer quant-backup.timer
systemctl status 'quant-*' --no-pager
```
1~2분 뒤 텔레그램으로 **새 휴대폰 주소·방문객 주소**가 옵니다(지금과 같은 방식).

## 9. 비용 관리
- **시간 단위**로 나가며, **꺼 둔(Stopped) 서버도 요금이 나갑니다.** 그만 쓰려면 **Destroy**(삭제)해야 멈춥니다.
- 월 요금 상한이 있어 한 달 내내 켜도 요금제 가격을 넘지 않습니다.

## 10. 자주 쓰는 명령 (서버)
| 하고 싶은 것 | 명령 |
|---|---|
| 전체 상태 | `systemctl status 'quant-*' --no-pager` |
| 스캐너 로그 | `journalctl -u quant-scanner -f` (나가기: Ctrl+C) |
| 전부 다시 켜기 | `systemctl restart 'quant-*'` |
| 아침 갱신 지금 | `systemctl start quant-cases` |
| 타임머신 | `sudo -u quant /home/quant/quant_system/venv/bin/python /home/quant/quant_system/timemachine.py 2` |
| 백업 목록 | `ls -lh /home/quant/backup` |
| R2 사본 목록 | `sudo -u quant bash -c 'set -a; . /home/quant/quant_system/.env; set +a; RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare RCLONE_CONFIG_R2_ACCESS_KEY_ID=$R2_ACCESS_KEY_ID RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=$R2_SECRET_ACCESS_KEY RCLONE_CONFIG_R2_ENDPOINT=https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com rclone lsl r2:$R2_BUCKET'` (매일 03:00 백업 뒤 `deploy/backup_db.sh` 가 올림 · R2_KEEP_DAYS 보관) |
| 차단된 IP 보기 | `fail2ban-client status sshd` |

## 11. 새 버전 적용 (서버)
```
copy "C:\Users\admin\OneDrive\바탕 화면\덕\공부\클로드\files\quant_system.zip" C:\quant_data\qs.zip
scp C:\quant_data\qs.zip root@서버IP:/root/
ssh root@서버IP "cd /root && python3 -m zipfile -e qs.zip /root/new && cp -a /root/new/quant_system/. /home/quant/quant_system/ && rm -rf /root/new && chown -R quant:quant /home/quant/quant_system && systemctl restart 'quant-*'"
```
(.env 와 DB 는 덮어쓰지 않습니다.)

## 12. 🔒 고정 주소 (도메인 + Cloudflare 이름 있는 터널)
주소가 `dash.내도메인.com` · `guest.내도메인.com` 으로 **다시는 바뀌지 않게** 합니다(터널은 무료, 도메인만 연 약 1.5만 원).
1. **도메인 사기**: dash.cloudflare.com 가입 → **Domain Registration → Register Domains** → 원하는 이름 검색 → 구매(.com 권장, 원가 판매).
   Cloudflare 에서 사면 DNS 가 자동으로 연결돼 가장 쉽습니다. Cloudflare 계정에도 **2단계 인증**을 켜 두세요.
2. **서버에서 한 번 실행** (도메인 이름을 바꿔 넣기):
   ```
   bash /home/quant/quant_system/deploy/setup_named_tunnel.sh 내도메인.com
   ```
   처음에 **긴 주소(https://dash.cloudflare.com/argotunnel?...)** 가 나오면 PC 브라우저에 붙여 넣고 → 로그인 → 도메인 선택 → **Authorize**.
   서버 창으로 돌아오면 나머지(터널 2개 만들기 · 주소 연결 · 설정 저장 · 재시작)는 자동입니다.
3. 텔레그램으로 **🔒 고정 주소**가 옵니다 → 휴대폰 브라우저에서 열고 **홈 화면에 추가**.
4. (선택·추천) **Cloudflare Access**: Zero Trust → Access → Applications → Self-hosted → `dash.내도메인.com` → 정책 "Emails: 내 이메일"
   → 대시보드 비밀번호 앞에 **이메일 인증 코드** 한 단계가 더 생깁니다(무료). 방문객 주소(guest)에는 걸지 마세요.

## 다음 단계 (이전이 끝나면)
- **Massive 실시간**: 서버 한 곳에서만 접속
- **AI PICK**: Anthropic API 로 공시를 읽고 '가장 빨리' 판단 + 🏆 성과 공표로 적중 검증
