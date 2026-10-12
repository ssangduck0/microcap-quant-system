import yfinance as yf
import time
import requests
import csv
import os
from datetime import datetime
import xml.etree.ElementTree as ET
from playwright.sync_api import sync_playwright

TELEGRAM_TOKEN = "8975468372:AAFJYnNp_r2F_NYfsm_ykje8v7Vpuegomy0"
CHAT_ID = "6116947302"
SEC_USER_AGENT = "MyStockScanner myemail@gmail.com" 

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": message})
    except:
        pass

def get_microcap_tickers():
    print("🔍 봇 방어막 우회 중... (데이터 누적 수집 모드)")
    tickers = []
    
    script_folder = os.path.dirname(os.path.abspath(__file__))
    profile_path = os.path.join(script_folder, "bot_profile")
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        page = context.pages[0] if context.pages else context.new_page()
        
        try:
            for i in range(1, 101, 20):
                target_url = f"https://finviz.com/screener?v=111&f=cap_micro,sh_price_u5&r={i}"
                print(f"📡 페이지 {i//20 + 1} 스캔 중...")
                
                try:
                    page.goto(target_url, timeout=60000, wait_until="commit")
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    time.sleep(3) 
                except:
                    pass
                
                js_extract = """
                () => {
                    let results = [];
                    let links = document.querySelectorAll('a');
                    for (let a of links) {
                        let txt = a.innerText.trim();
                        if (/^[A-Z]{1,5}$/.test(txt)) {
                            results.push(txt);
                        }
                    }
                    return results;
                }
                """
                try:
                    page_tickers = page.evaluate(js_extract)
                    if page_tickers:
                        tickers.extend(page_tickers)
                except:
                    pass
                
                time.sleep(1) 
                
        except Exception as e:
            print(f"⚠️ 핀비즈 스캔 중 에러 발생: {e}")
        finally:
            context.close() 
            
    tickers = list(set(tickers))
    ignore_list = ['HOME', 'NEWS', 'MAPS', 'GROUPS', 'HELP', 'ELITE', 'LOGIN', 'ANY', 'USA', 'ETF']
    valid_tickers = [t for t in tickers if t not in ignore_list and t.isalpha() and t.isupper() and 1 <= len(t) <= 5]
    
    print(f"✅ 총 {len(valid_tickers)}개의 초소형주 신규 발굴 완료!")
    
    return valid_tickers if valid_tickers else ["WCT", "BNAI", "CLDI", "WHLR"]

def check_sec_risk(ticker):
    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=&dateb=&owner=exclude&start=0&count=5&output=atom"
    headers = {'User-Agent': SEC_USER_AGENT}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200: return "⚠️ SEC 서버 지연"
        root = ET.fromstring(response.content)
        risk_keywords = ["8-K", "S-1", "S-3", "424B5", "Offering", "Warrant", "Dilution"]
        for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
            title = entry.find('{http://www.w3.org/2005/Atom}title').text
            for keyword in risk_keywords:
                if keyword.upper() in title.upper():
                    return f"🚨 [위험공시] {title}"
        return "✅ 특이 희석 공시 없음"
    except:
        return "⚠️ SEC 확인 불가"

tickers = get_microcap_tickers()

script_folder = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(script_folder, "stock_record.csv")

# 파일이 없으면 헤더 생성
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode='w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file)
        writer.writerow(["포착시간", "티커", "현재가", "1분_거래량", "평균대비_배수", "SEC_공시상태"])

print(f"🚀 {len(tickers)}개 종목에 대한 실시간 퀀트 수집 엔진 가동...")
send_telegram(f"시스템 가동: 🔍 {len(tickers)}개 초소형주 감시 시작 (데이터 누적 모드) 🚀")

while True:
    for ticker in tickers:
        try:
            hist_20d = yf.Ticker(ticker).history(period="20d", progress=False)
            avg_vol = hist_20d['Volume'].mean() if not hist_20d.empty else 0
            
            data_1m = yf.Ticker(ticker).history(period="1d", interval="1m", prepost=True, progress=False)
            
            if not data_1m.empty:
                current_price = data_1m['Close'].iloc[-1]
                current_volume = data_1m['Volume'].iloc[-1]
                
                multiple = current_volume / avg_vol if avg_vol > 0 else 0
                
                # 테스트 및 누적 확인을 위해 조건 만족 시 무조건 히스토리에 차곡차곡 쌓이도록 기록
                sec_status = check_sec_risk(ticker)
                now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # ★ 데이터 유실 없이 순수 누적(Append) 방식으로 기록
                with open(CSV_FILE, mode='a', newline='', encoding='utf-8-sig') as file:
                    writer = csv.writer(file)
                    writer.writerow([now_time, ticker, f"${current_price:.4f}", current_volume, f"{multiple:.2f}", sec_status])
                
                print(f"💾 {ticker} 누적 기록 저장! 현재가: ${current_price:.4f} / 배수: {multiple:.2f}배")
                    
        except Exception as e:
            pass 
            
    print("--- 1 사이클 완료. 60초 대기 중 ---")
    time.sleep(60)