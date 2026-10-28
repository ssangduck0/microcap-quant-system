"""'점수 검증' 탭: 승률 점수 모델이 실제로 맞는지(표본 외 검증 + 라이브 성과)를 보여준다."""
import numpy as np
import pandas as pd
import streamlit as st

import config
import db
import winmodel


def auc_comment(a: float | None) -> str:
    if a is None:
        return "-"
    if a < 0.53:
        return "무작위에 가깝습니다 — 이 점수로는 거르기 어렵습니다"
    if a < 0.58:
        return "약한 신호"
    if a < 0.65:
        return "의미 있는 신호"
    return "강한 신호 (과적합/누수가 없는지 의심해 볼 만큼 높음)"


@st.cache_data(ttl=60)
def load_models() -> list[dict]:
    return db.list_models()


@st.cache_data(ttl=60)
def load_live() -> pd.DataFrame:
    return db.read_df("SELECT s.date, s.ticker, s.win_p, s.win_score, s.win_model, s.dilution_status, e.next_high_pct, e.next_close_pct "
                      "FROM daily_snapshots s JOIN case_events e ON e.ticker=s.ticker AND e.date=s.date")


def render_sigmodel() -> None:
    """🧠 신호 승률 모델(우리만의 AI 2단계, sigmodel): 승률 점수와 같은 models 표에 저장되지만 입력·목표가 달라 따로 보여 준다(2026-10-28).
    이 모델이 10/28 에 처음 저장되면서 위 선택 상자가 이름을 '종류_목표' 로 쪼개다 KeyError 로 죽었음 → 선택 상자는 승률 모델만, 🧠 은 여기."""
    st.markdown("### 3. 🧠 신호 승률 모델 — 신호(📐·🚦·매집 등)가 난 뒤 큰 목표/작은 목표에 닿을 확률")
    try:
        sm = db.get_model("sigmodel")
    except Exception:  # noqa: BLE001
        sm = None
    if not sm or not isinstance(sm.get("targets"), dict):
        st.info("아직 학습되지 않았습니다(토요일 아침 작업에서 월 1회 학습 · 서버에서 `sigmodel.py fit`).")
        return
    try:
        import sigmodel
        st.caption(sigmodel.summary(sm))
    except Exception:  # noqa: BLE001
        st.caption(f"표본 학습 {sm.get('n_train') or 0:,} · 검증 {sm.get('n_test') or 0:,} · 검증 시작 {sm.get('cutoff') or '-'} · 학습 시각 {sm.get('fitted_at') or '-'}")
    cols = st.columns(2)
    for col, key, title in zip(cols, ("p30", "p10"), ("p30 · 큰 목표", "p10 · 작은 목표")):
        t = sm["targets"].get(key) or {}
        with col:
            st.markdown(f"**{title}** — {t.get('horizon', '?')}거래일 안 +{t.get('target_pct', '?')}%")
            a, b, c = st.columns(3)
            a.metric("검증 AUC", "-" if t.get("auc_test") is None else f"{t['auc_test']:.3f}", help=auc_comment(t.get("auc_test")))
            b.metric("기준 적중", "-" if t.get("base_rate_test") is None else f"{t['base_rate_test']:.1f}%", help="확률과 무관하게 검증 구간 신호 전체의 적중 비율")
            c.metric("상위 10% 배수", "-" if t.get("lift_top") is None else f"×{t['lift_top']:.2f}", help="예측 확률 상위 10% 신호의 적중률 ÷ 기준 적중")
    st.caption("확률 분위표·특징 가중치·다시 학습 버튼은 🔍 부검 탭의 🧠 구역에 있어요(같은 모델). 라이브 적중(🏆 성과 공표의 🧠 확률 분위)은 11/15~22 에 함께 봅니다.")


def render() -> None:
    st.subheader("🧪 승률 점수 검증")
    # 2026-10-28: models 표에는 🧠 sigmodel 같은 다른 모델도 저장된다 → 승률 모델(label·target·metrics 가 있는 것)만 고른다(안 그러면 아래 selectbox 가 KeyError)
    models = [m for m in load_models() if m.get("label") in winmodel.LABELS and m.get("target") is not None and isinstance(m.get("metrics"), dict)]
    if not models:
        st.info("아직 학습된 모델이 없습니다. 과거 사례 DB를 만든 뒤(`python cases.py build --years 10`) "
                "`python winmodel.py fit` 을 실행하세요.")
        return
    names = [m["name"] for m in models]
    by = {m["name"]: m for m in models}
    default = names.index(config.WIN_MODEL) if config.WIN_MODEL in names else 0
    pick = st.selectbox("검증할 모델", names, index=default, key="score_model",
                        format_func=lambda n: f"{n}  ({winmodel.LABELS[by[n]['label']][1]} ≥ +{by[n]['target']:g}%)")   # 이름을 쪼개지 않고 저장된 값으로
    md = by[pick]
    m = md["metrics"]
    label_ko = winmodel.LABELS[md["label"]][1]
    st.caption(f"입력 {len(md['features'])}개({md.get('feature_set', 'v1')}) · {'2차(상호작용 포함)' if md.get('quad') else '선형'} 모델 · "
               f"'성공' = {label_ko}가 사건일 종가 대비 +{md['target']:g}% 이상 · 학습 시각 {md['fitted_at']} (UTC) · "
               f"점수 기준 모델로 스캐너에 기록되는 것은 `{config.WIN_MODEL}` (`.env` 의 WIN_MODEL 로 변경)")

    st.markdown("### 1. 표본 외(OOS) 검증 — 학습에 쓰지 않은 최근 구간")
    if "auc_test" not in m:
        st.warning(m.get("note", "표본 외 검증 결과가 없습니다."))
    else:
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("OOS AUC", f"{m['auc_test']:.3f}", help="0.5=무작위, 1.0=완벽. 학습 구간 AUC와 크게 차이 나면 과적합")
        k2.metric("기준 성공률(검증 구간)", f"{m['base_rate_test']:.1f}%", help="점수와 무관하게 이 구간 급락 사건 전체의 성공 비율")
        k3.metric("상위 20% 점수 성공률", f"{m['rate_top20']:.1f}%", delta=f"×{m['lift_top20']:.2f} 배", delta_color="off")
        k4.metric("학습 구간 AUC", f"{m['auc_train']:.3f}")
        k5.metric("검증 구간", f"{m['test_from']} ~", help=f"학습 {m['n_train']:,}건 / 검증 {m['n_test']:,}건")
        lin = f" (같은 입력의 선형 모델은 {m['auc_linear_test']:.3f})" if m.get("auc_linear_test") is not None else ""
        st.info(f"해석: OOS AUC {m['auc_test']:.3f}{lin} → **{auc_comment(m['auc_test'])}**. "
                f"점수가 높은 구간이 실제로 더 자주 성공했는지는 아래 표로 확인하세요.")

        st.markdown("**점수 임계값별 표본 외 성과** (점수 ≥ X 로 거르면?)")
        th = pd.DataFrame(m["thresholds"]).rename(columns={
            "score": "점수 ≥", "n": "검증 구간 사건 수", "success": "성공률(%)", "lift": "기준 대비 배수",
            "close_median": "다음날 종가 중앙값(%)", "close_mean": "다음날 종가 평균(%)", "close_up": "종가 상승 비율(%)",
            "tp_mean": "목표가 청산 평균(%)", "tp_median": "목표가 청산 중앙값(%)", "tp_win": "청산 승률(%)", "tp_tail": "-20%↓ 손실 비율(%)"})
        th = th.dropna(axis=1, how="all")  # 종가 기준 모델에는 목표가 청산 열이 없다
        st.dataframe(th, hide_index=True, width="stretch", column_config={
            c: st.column_config.NumberColumn(format="%.2f" if c == "기준 대비 배수" else "%.1f") for c in th.columns if c not in ("점수 ≥", "검증 구간 사건 수")})
        btp = m.get("base_tp")
        if btp:
            st.info(f"**목표가 청산 시뮬레이션** — 사건일 종가에 사서 다음날 **+{md['target']:g}% 지정가 매도**를 걸고, 못 팔면 다음날 종가에 정리(갭 시작이면 시가에 체결 가정). "
                    f"전체 사건 기준: 목표 도달 {btp['hit']:.1f}% · **평균 {btp['mean']:+.1f}%** · 중앙값 {btp['median']:+.1f}% · 승률 {btp['win']:.1f}% · "
                    f"-20% 이하 손실 {btp['tail']:.1f}%.  점수가 높은 구간에서 '평균'과 '승률'이 전체보다 높고 '-20% 이하 손실 비율'이 낮아야 쓸모가 있습니다. "
                    "체결 수량·호가 공백·거래정지·수수료는 반영되지 않은 낙관적 수치입니다.")
        bc = m.get("base_close")
        if bc:
            st.caption(f"전체 사건 기준: 다음날 종가 중앙값 {bc['median']:+.1f}% · 평균 {bc['mean']:+.1f}% · 상승 비율 {bc['up']:.1f}%.  "
                       "**'성공률'(고가 기준)은 고가에 팔 수 없어 실제 수익이 아닙니다.** 점수가 올라갈 때 '다음날 종가 중앙값·평균·상승 비율'도 함께 올라가야 "
                       "거래 가능한 우위입니다. 평균은 극단값을 -50~+100%로 제한한 값이며, 수수료·호가 공백·거래정지는 반영되지 않았습니다.")
        st.caption("임계값을 여러 번 바꿔 보며 가장 좋은 승률만 고르면 과적합입니다. 이 표에서 기준을 한 번 정하고, 아래 '라이브 성과'로 확인하세요. "
                   "사건 수가 적은 높은 임계값의 성공률은 우연에 크게 흔들립니다.")

        st.markdown("**확률 보정표** (예측한 확률과 실제 비율이 맞는가)")
        dec = pd.DataFrame(m["deciles"]).rename(columns={"bin": "10분위(낮음→높음)", "pred": "예측 확률(%)", "actual": "실제 성공률(%)", "n": "사건 수"})
        c1, c2 = st.columns([1, 1])
        c1.dataframe(dec, hide_index=True, width="stretch", column_config={
            "예측 확률(%)": st.column_config.NumberColumn(format="%.1f"), "실제 성공률(%)": st.column_config.NumberColumn(format="%.1f")})
        c2.line_chart(dec.set_index("10분위(낮음→높음)")[["예측 확률(%)", "실제 성공률(%)"]])

    st.markdown("### 2. 모델이 보는 입력값")
    co = pd.DataFrame(md["coefs"])
    co["영향"] = co["std_coef"].map(lambda c: "클수록 성공확률↑" if c > 0 else "클수록 성공확률↓")
    st.dataframe(co.rename(columns={"label": "입력값", "std_coef": "표준화 계수"})[["입력값", "표준화 계수", "영향"]], hide_index=True, width="stretch",
                 column_config={"표준화 계수": st.column_config.NumberColumn(format="%.3f")})
    st.caption(f"입력값은 가격·거래량·시장 지표 {len(md['features'])}개뿐입니다{' (계수는 선형 모델 기준 참고값)' if md.get('quad') else ''}. 공시(희석) 정보는 과거 시점별로 재현하지 못해 학습에 들어가지 않았고, "
               f"점수에는 가정 배수만 곱합니다: {config.DILUTION_MULT} (보정 {'켜짐' if config.DILUTION_ADJUST else '꺼짐'}).")

    render_sigmodel()
    st.markdown("### 4. 라이브 성과 — 스캐너가 기록한 점수 vs 실제 결과")
    live = load_live()
    col = winmodel.LABELS[md["label"]][0]
    live = live.dropna(subset=[col]).copy()
    if live.empty:
        st.info("아직 비교할 데이터가 없습니다. 스캐너가 점수를 기록한 종목이 장 마감 후 `python cases.py update` 로 결과가 채워져야 여기에 나타납니다.")
        return
    live["성공"] = live[col] >= md["target"]
    st.caption("스캐너가 정규장 마지막 스캔에서 기록한 값(재계산 아님)과, 그날 종가 기준 급락 사건의 실제 결과를 붙였습니다. "
               "종가에 -10% 이하로 마감하지 않은 종목은 사건이 아니라 제외됩니다.")
    scored = live[(live["win_model"] == pick) & live["win_score"].notna()].copy()
    a, b, c = st.columns(3)
    a.metric("결과가 확인된 점수 기록", f"{len(scored):,}")
    b.metric("전체 성공률(점수 기록분)", f"{scored['성공'].mean() * 100:.1f}%" if len(scored) else "-")
    c.metric("기록 기간", f"{scored['date'].min()} ~ {scored['date'].max()}" if len(scored) else "-")
    if len(scored) < 30:
        st.warning(f"표본이 {len(scored)}건뿐이라 아직 판단하기 이릅니다. 최소 수십~수백 건이 쌓인 뒤에 보세요.")
    if len(scored):
        bands = pd.cut(scored["win_score"], [-0.1, 50, 70, 85, 100.1], labels=["0~50", "50~70", "70~85", "85~100"])
        t = scored.groupby(bands, observed=True).agg(사건_수=("성공", "size"), 성공률=("성공", lambda s: s.mean() * 100)).reset_index()
        t.columns = ["승률 점수 구간", "사건 수", "성공률(%)"]
        st.dataframe(t, hide_index=True, width="stretch", column_config={"성공률(%)": st.column_config.NumberColumn(format="%.1f")})
        st.caption("점수가 높은 구간일수록 성공률이 높아야 정상입니다. 그렇지 않거나 OOS 표와 크게 다르면 모델을 믿지 마세요.")

    st.markdown("**희석 상태별 실측 성공률** — 점수의 가정 배수를 교체할 근거")
    d = live.groupby("dilution_status").agg(사건_수=("성공", "size"), 성공률=("성공", lambda s: s.mean() * 100)).reset_index()
    d.columns = ["희석 상태", "사건 수", "성공률(%)"]
    d["현재 가정 배수"] = d["희석 상태"].map(config.DILUTION_MULT)
    st.dataframe(d, hide_index=True, width="stretch", column_config={"성공률(%)": st.column_config.NumberColumn(format="%.1f")})
    st.caption("CLEAN 대비 상대 성공률이 가정 배수와 크게 다르고 사건 수가 충분(상태별 100건 이상)해지면 `config.py` 의 DILUTION_MULT 를 실측 비율로 바꾸세요.")
