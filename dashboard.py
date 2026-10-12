import streamlit as st
import pandas as pd
import os

st.set_page_config(layout="wide", page_title="배상덕: 초소형주 퀀트 대시보드", page_icon="🚀")

st.title("🚀 배상덕: 초소형주 퀀트 대시보드")
st.markdown("나스닥 초소형주(Micro-cap) 실시간 거래량 폭발 및 SEC 공시 감시 엔진")

def calculate_quant_score(row):
    score = 50.0
    try:
        vol_multiple = float(row.get('평균대비_배수', 1.0))
        score += min(vol_multiple * 5.0, 30.0)
    except:
        pass
        
    sec_status = str(row.get('SEC_공시상태', ''))
    if "위험" in sec_status:
        score -= 40.0 
    elif "특이 희석 공시 없음" in sec_status:
        score += 15.0 
        
    return round(max(min(score, 99.9), 0), 2)

csv_path = "stock_record.csv"
df = pd.DataFrame(columns=["포착시간", "티커", "현재가", "1분_거래량", "평균대비_배수", "SEC_공시상태"])

if os.path.exists(csv_path):
    try:
        temp_df = pd.read_csv(csv_path)
        if not temp_df.empty and '티커' in temp_df.columns:
            df = temp_df.dropna(subset=['티커'])
            df = df.sort_values(by="포착시간", ascending=False).drop_duplicates(subset=['티커'], keep='first')
    except:
        pass

if not df.empty and '티커' in df.columns:
    df['유사도_점수(Score)'] = df.apply(calculate_quant_score, axis=1)
    df = df.sort_values(by="유사도_점수(Score)", ascending=False)

tab1, tab2, tab3 = st.tabs(["📊 실시간 퀀트 포착", "📅 공시 D-Day 달력", "📈 패턴 타임라인 분석"])

with tab1:
    col1, col2, col3 = st.columns(3)
    
    unique_count = len(df['티커'].unique()) if not df.empty and '티커' in df.columns else 0
    col1.metric("오늘 포착된 종목 수", f"{unique_count} 개")
    
    if not df.empty and '티커' in df.columns and len(df) > 0:
        best_ticker = df.iloc[0]['티커']
        best_score = df.iloc[0].get('유사도_점수(Score)', 50.0)
        col2.metric("🔥 현재 1위 유망 종목", str(best_ticker), f"{best_score} 점")
    else:
        col2.metric("🔥 현재 1위 유망 종목", "거래량 폭발 대기 중", "0 점")
        
    col3.metric("엔진 가동 상태", "ON (실시간 감시 중) 🟢")

    st.markdown("---")
    st.subheader("실시간 포착 데이터베이스 (최신 갱신순)")

    if not df.empty and '티커' in df.columns and len(df) > 0:
        display_cols = [c for c in ["유사도_점수(Score)", "포착시간", "티커", "현재가", "1분_거래량", "평균대비_배수", "SEC_공시상태"] if c in df.columns]
        display_df = df[display_cols]
        
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "유사도_점수(Score)": st.column_config.ProgressColumn(
                    "유사도 점수",
                    help="과거 급등 패턴과의 유사도 (100점 만점)",
                    format="%.2f 점",
                    min_value=0,
                    max_value=100,
                ),
                "평균대비_배수": st.column_config.NumberColumn(
                    "거래량 폭발 배수",
                    format="%.1f 배 💥"
                ),
                "현재가": st.column_config.TextColumn("현재가 (USD)"),
                "SEC_공시상태": st.column_config.TextColumn("공시 리스크 판독")
            }
        )
    else:
        st.info("💡 현재 평소 대비 3배 이상 거래량이 폭발한 초소형주를 대기 중입니다...")

with tab2:
    st.subheader("주요 종목 공시 및 이벤트 감시 목록")
    st.markdown("S-1, 8-K, 액면병합(Reverse Split) 등 주요 일정을 추적합니다.")
    
    dday_data = pd.DataFrame([
        {"항목": "WHLR 10월 병합 8-K", "예상 시점": "10/26~11/3 예상", "남은 날": "D-9", "상태": "대기", "중요도/비고": "1달러 미만 마감 카운트 시작"},
        {"항목": "공매도 잔고 발표", "예상 시점": "10/26", "남은 날": "D-14", "상태": "대기", "중요도/비고": "급등 뒤 하락 구간 커버링 여부 확인"},
        {"항목": "상환 결과 8-K", "예상 시점": "11/6", "남은 날": "D-25", "상태": "대기", "중요도/비고": "병합 펌핑이 계산 기간 안에 들어오는지 핵심"}
    ])
    
    st.dataframe(dday_data, use_container_width=True, hide_index=True)

with tab3:
    st.subheader("급등/급락 사이클 추적")
    st.markdown("과거 10일 VWAP 앵커 추정 및 사이클 고점·저점 위치 판독")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info("📉 그라인드 다운 (Grind Down)\n\n현재 유통주식 급증으로 인한 하락 사이클 진행 중")
    with col2:
        st.warning("⚠️ 상환 출회\n\n사체 전환가 아래로 눌림 발생. 전환 유인 없음")
    with col3:
        st.success("🚀 병합 펌핑 대기\n\n1달러 규칙 미달로 인한 30거래일 전 병합 필요 구간 진입")