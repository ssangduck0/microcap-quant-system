# 🎲 매매 전 시뮬레이션 — 더 좋은 방법 조사(2026-10-30 새벽 · 사용자 "시간이 걸려도 좋으니 래빗스탁 같은 사이트는 어떤 방법을 쓰는지 찾아 줘")

조사 범위: 래빗스탁 공식 가이드 페이지 전부 · 해외 서비스(Trade Ideas OddsMaker · Tickeron · TrendSpider · Edgewonk · DilutionTracker) 공식 문서와 리뷰 · 학계·실무 표준(López de Prado 의 triple-barrier/메타 라벨링/표본 가중/백테스트 과적합, 확률 보정, 소표본 보정, 단기 반전 문헌, 이중 장벽 확률 공식). 서버 자료는 건드리지 않음.

## 0. 한 줄 결론
**래빗스탁에는 "이 매매가 과거에 통했나"를 재는 기능이 없다**(스캐너 + 점수 + AI 등급뿐, 승률·백테스트·시뮬레이션 전무). 해외 유료 서비스 중 가장 가까운 것은 Trade Ideas 의 **OddsMaker**(신호가 났던 과거 시점마다 가상 매매 → 승률·평균 손익·profit factor)와 Tickeron 의 **"비슷한 과거 사례 적중률"**인데, 둘 다 우리 presim 1겹(같은 신호 전체 과거에 내 손절·목표 적용)과 같은 발상이고 방법 공개는 우리보다 적다. 우리가 쓰는 "손절·목표·기간 세 장벽" 방식은 학계에서 **triple-barrier** 라 부르는 표준이다. 따라서 방향을 바꿀 이유는 없고, **표준에서 우리가 빠뜨린 보강 6가지**(아래 5절)를 11-5 구현안에 얹는 것이 답이다.

## 1. 래빗스탁은 어떻게 하나(공식 가이드 기준)
| 도구 | 방법(가이드 설명) | 확률·백테스트 | 우리 |
|---|---|---|---|
| 매집 스캐너 | 거래량이 평소의 몇 배인데 주가는 안 흔들린 종목(배수·안정 기준 비공개) | 없음 | 🧲 매집 의심(흡수일 규칙·점수 공개) ✅ |
| 매집 트리거(유료) | 수급·다크풀·구조(바닥)·거래량 확인 4요소 **매집 스코어** → A/B/주의/중립 등급 · 다크풀 비중 20일 평균·5일 vs 20일 Z-점수·'은닉 매집 다이버전스'(20일 +3% 이하인데 다크풀 Z>0.5) | 없음 | 🕶 다크풀(비중·괴리·연속) + 🧲 'DP 동반' 칩 — Z-점수·다이버전스 규칙은 **가져올 만함** |
| D-DAY 분석기 | 사용자가 정한 급등 기준(상승률·거래량 배율·평균 기간·반복 횟수·쿨다운)으로 **과거 급등일을 찾아 시각화**. 날짜·목표가 '예측'은 아님 | 없음 | 🔬 이벤트 연구 · 📚 과거 사례 · 🕰 타임머신이 더 깊음 |
| GEM 폭풍의 눈 | 거래량 진공(평균 대비 급감) + 52주 바닥권 태그 | 없음 | 🕰 타임머신 조건으로만(3절 결정) |
| 스퀴즈 랭크 · Reg SHO · 13D/G · 내부자 · 펀드스캔 · RS 스캐너 · 뉴스 A~C 등급 | 공개 자료 수집·순위·AI 등급 | 없음 | 모두 보유(10/27 B·C 단계) |
| 상하킷(LULD) 알림 | 변동성 정지 밴드 접촉 알림 | — | 없음(거래정지 현황만) — 작은 후보 |
→ 래빗스탁은 "찾아 주는 도구"이고, "찾은 것이 통했나"는 전적으로 사용자 몫이다. 우리는 찾는 도구 + 검증 층(🕰 타임머신 · 🏆 성과 공표 · 🧪 가상매매 · 🎲 presim)을 둘 다 가진 셈.

## 2. 해외 서비스는 어떻게 하나
| 서비스 | 방법 | 배울 점 | 한계 |
|---|---|---|---|
| **Trade Ideas OddsMaker** | 알림(필터)이 **과거에 울렸던 모든 시점**을 가상 매매로 바꿔(진입 = 알림, 청산 = 손절 % · 목표 · 보유 시간 · 장 마감) 승률 · 평균 이익/손실 · profit factor · 최대 낙폭 · 연속 손실 · 자본 곡선 · 결과 분포를 보여 줌. 1분봉 OHLC 기준(틱 아님, 스프레드 무시), 같은 종목은 하루 한 번만 진입, 프리·애프터 제외. 사용 지침: "표본이 적으면 결론 없음" · 알림 10건은 차트로 눈검사 · 통과 기준(최소 건수·PF·낙폭)을 미리 정하기 · **모의 30세션 전진 검증** · 전략 수정이나 **체제 변화 뒤 재실행** | ① 최근 창(수개월) 성적을 따로 보는 습관 ② 통과 기준을 미리 정하기 ③ 전진 검증(=우리 🏆 성과 공표 역할) | 과거 깊이가 짧음(64일 언급) · 방법 세부 비공개 |
| **Tickeron 패턴 검색** | 지금 모양과 **비슷했던 과거 사례**를 찾아 그 뒤 결과의 적중률을 "odds of success"(예: 4건 중 3건 상승 = 75%)로, 별도 'confidence' 필터(20~80%) | 유사 사례 층(우리 '유사 사례 수' 열과 같은 발상) | 공식 비공개 · 자체 발표 성공률이 서로 다름 · 표본 4건으로 75% 를 말하는 식 |
| **TrendSpider** | 전략 테스터(진입·청산·손절·목표·수수료·슬리피지) · 500+ 종목 동시 테스트 · **파라미터 변형 52개 한 번에**(변수 조금 바꿔도 우위가 남는지) · 유사 셋업 찾기 | 파라미터 민감도 점검 | 몬테카를로·walk-forward 없음(리뷰) |
| **Edgewonk(매매 일지)** | 셋업 태그별 **기대값(R)** · profit factor · 낙폭 · Monte Carlo 자본 곡선 | 📒 매매 일지에 '근거 신호별 기대값' 은 이미 있음 | — |
| **DilutionTracker** | 유통주식(발행 − 내부자 − 5%↑ 보유 + 공시 뒤 발행) · 현금 소진(현금 ÷ 월 소모) · 발행 여력(S-3 선반 잔여 · ATM 잔여 · S-1 대기) → 희석 위험 종합 점수 | 우리 공시분석·런웨이·물량 장부와 같은 재료 — '발행 여력'을 한 숫자로 | 확률 모델 아님 |

## 3. 학계·실무 표준과 우리 위치
| 개념 | 내용 | 우리 presim |
|---|---|---|
| **Triple-barrier**(López de Prado, *Advances in Financial ML* 3장) | 사건마다 익절·손절·시간 세 장벽 중 먼저 닿은 것으로 라벨. 종가만이 아니라 **고·저가로 터치 확인** · 매 봉이 아니라 **사건(신호)만 표본** | ✅ 같은 방식(`outcomes`: 고·저가 · 같은 날 둘 다면 보수적으로 손절 · 신호가 처음 켜진 날만) |
| 표본 겹침 가중(uniqueness, 4장) | 같은 종목의 사건이 40봉씩 겹치면 독립 표본이 아님 → 겹침 정도로 가중해 '유효 표본'을 셈 | ❌ 없음 — 사건 수를 그대로 n 으로 표시 |
| 메타 라벨링(3장) | 1차 모델이 방향(산다)을 정하면 2차 모델이 "이번 건은 성공할까"를 예측해 크기 조절 | 🧠 sigmodel 이 그 역할(신호별 p30·p10) — presim 과 **아직 안 묶임** |
| 체제(regime) 조건 | 장세별로 통계가 다르면 지금 장세와 같은 사건만 보기 | 🚦 장세 신호등·`regime_hist` 있음 — presim 사건 표에 **안 붙음** |
| 소표본 보정(empirical Bayes) | 승률 = (성공 + α)/(건수 + α + β), α+β = '가짜 표본 수' κ → 표본이 적을수록 전체 평균 쪽으로 끌림(κ/(κ+n)) | ❌ 없음 — 2024년 저금통 24건 "익절 50%" 처럼 작은 표본이 그대로 보임 |
| 확률 보정(Brier · reliability diagram) | 예측 확률 구간별 실제 적중률을 그려 과신을 잡음. 나무 모델은 과신 경향(실제 55% 를 65~80% 로) | 🏆 성과 공표가 재료 — presim_g/c/r 를 **구간별 실제 익절률**로 그리는 것까지는 없음 |
| 백테스트 과적합(DSR · PBO, Bailey & López de Prado) | 변형을 많이 시도해 가장 좋은 것만 고르면 성적이 부풀려짐 · 최소 검증 기간 | presim 은 '사용자 계획 하나'를 재는 도구라 탐색이 적음 — **자동 최적화는 넣지 말 것**(원칙으로 기록) |
| 이중 장벽 확률 공식(GBM) | 드리프트 0 이면 로그 척도에서 P(익절 먼저) = ln(매수가/손절가) ÷ ln(목표가/손절가). 단순 기대값 0 기준은 **p = 손절폭/(손절폭+목표폭)** | ❌ 화면에 "동전 던지기라면 몇 %" 기준선이 없음 — 숫자 해석에 바로 도움(예: −10/+30 이면 25% · 저금통 중앙값 −8.9/+32.1 이면 21.7%) |
| 단기 반전 문헌 | 반전은 소형·비유동·고회전·하락 종목에서 강하지만, 논문 대부분이 **$5 미만을 제외** → 초소형주 직접 근거는 거의 없음 | 우리 2년 사건 표가 오히려 드문 자료 — 계속 쌓을 가치 |

**우리 숫자를 공식에 대 보면**: 기준(아무 날) 사건의 −10/+30 익절 19% 는 기대값 0 기준 25% 보다 낮다 → 초소형주 아무 날은 **마이너스 드리프트**. 저금통 재생 익절 25%(박스 중앙값 계획 기준 21.7%)·⭐1 21%(기준 25%) 처럼 **기준선과 나란히 보여 주면** "좋다/나쁘다"를 색이 아니라 숫자로 읽을 수 있다.

## 4. 우리 presim 의 갖춘 것 / 빠진 것
| 갖춤 ✅ | 빠짐 ❌ |
|---|---|
| triple-barrier 1겹(2년 × 전체 종목, 신호 첫날만, 고·저가 터치, 보수/낙관 범위) · 2겹 블록 부트스트랩 · 수량 · 미완성 봉 제외 · 자가 치유 · 🏆 전진 검증 · 🧠 메타 모델 · 🚦 장세 · 📒 일지 기대값 | 기준 대비 우위 판정 · 소표본 보정 · 최근 창 성적(쇠퇴 감지) · 체제 조건부 · 겹침 가중(유효 표본) · 보정 그래프 · 기대값 0 기준선 표시 · 메타 모델과의 결합 |

## 5. 추천 — 11-5 구현안에 얹을 보강 6가지(우선순위 순)
| # | 보강 | 왜 | 공수 |
|---|---|---|---|
| F | **기대값 0 기준선** 표시: "동전 던지기라면 익절 x%" 한 줄 + 1겹 결과와 나란히 | 숫자 해석이 바로 됨 · 비용 0 | 10분 |
| A | **기준 대비 우위 + 소표본 보정**: edge = ev − ev_base, 표본 n 이 적으면 κ=100 상당으로 기준 쪽으로 끌어 판정(🟢 edge ≥ +1%p & 유효 표본 ≥100 · 🔴 ≤ −1%p) | 지금 "거의 다 🪙" 와 "24건으로 +13.9%" 둘 다 해결 | 1시간 |
| B | **최근 창 성적** 병기: 최근 120거래일 사건만의 익절·손절·기대값(OddsMaker 식) + 연도별 | 저금통 2026 쇠퇴 같은 변화를 화면에서 보이게 | 1시간 |
| C | **체제 조건부**: 사건 표에 그날 🚦 장세(0~2) 저장(`ALTER ADD regime`) → "오늘 장세와 같은 사건만" 통계를 함께 | 장세가 나쁠 때 좋은 신호도 죽는 걸 분리 | 2시간(regime_hist 는 10/28 부터 → 그 전은 VIX·SPY 200일선으로 재계산) |
| D | **겹침 가중**: 같은 종목 40봉 안 연속 사건을 1/겹침 수로 가중 → '유효 표본' 표시 | n 과신 방지(저금통 384건의 유효 표본은 더 적을 것) | 1시간 |
| E | **보정 그래프**: 🏆 presim 출처의 예측 익절확률 구간(10%p)별 실제 익절률 + Brier | 몇 주 뒤 "presim 이 맞는 말을 하나"를 숫자로 | 2시간(자료 쌓인 뒤) |
| (후순위) | 유사 사례 층(kNN) · 메타 모델 결합(sigmodel p30 을 presim 카드에 병기) · 래빗 식 다크풀 Z-점수·은닉 매집 다이버전스 칩 | 근거 문헌 약함 / 별도 일감 | — |
원칙 하나 추가: **presim 은 자동 최적화를 하지 않는다**(키·손절·목표 조합을 탐색해 가장 좋은 것을 고르는 기능 금지 — 과적합 확률 PBO). 사용자가 정한 계획 하나를 재고, 결과는 🏆 전진 검증으로 확인한다.

## 6. 출처
- 래빗스탁: [가이드](https://rabbitstock.com/guide) · [D-DAY 분석기](https://rabbitstock.com/guide/tools/surge-day) · [매집 트리거](https://rabbitstock.com/guide/tools/trigger) · [GEM](https://rabbitstock.com/guide/tools/gem)
- Trade Ideas: [OddsMaker Backtesting Guide](https://www.trade-ideas.com/learning-center/backtesting-strategy-development/oddsmaker-backtesting-guide/) · [User Guide 9.9 Backtest Strategy](https://www.trade-ideas.com/guide/chapter/9_9/9.9Backtest_Strategy.html) · [Backtesting features](https://www.trade-ideas.com/features/backtesting/)
- Tickeron: [Pattern Search Engine](https://tickeron.com/trading-investing-101/harnessing-the-power-of-search-engines-to-uncover-trading-opportunities/) · [Real-Time Patterns](https://tickeron.com/trading-investing-101/stocks-and-etfs-ai-real-time-patterns/)
- TrendSpider: [Find High-Quality Trading Ideas](https://trendspider.com/product/find-high-quality-trading-ideas/) · [리뷰(변형 테스트·한계)](https://www.liberatedstocktrader.com/trendspider-review-automated-stock-trend-analysis/) · [backtestscore 리뷰](https://www.backtestscore.com/tools/trendspider)
- Edgewonk: [Expectancy 도움말](https://edgewonk.zendesk.com/hc/en-us/articles/360010177319-Expectancy) · [지표 설명](https://tradeciety.com/all-edgewonks-metrics-and-statistics-explained-for-successful-journaling)
- DilutionTracker: [How It Works](https://www.dilutracker.com/how-it-works) · [리뷰](https://www.findmymoat.com/tools/dilution-tracker)
- Triple-barrier·메타 라벨링·가중: [Halley Tech 정리](https://halleytech.substack.com/p/triple-barrier-meta-labeling-quant-research) · [Reasonable Deviations 노트](https://reasonabledeviations.com/notes/adv_fin_ml/) · [Quantmemo](https://www.quantmemo.com/concepts/triple-barrier-labeling) · [Quantt](https://www.quantt.co.uk/resources/triple-barrier-method) · [HMA Quant](https://hmaquant.substack.com/p/the-triple-barrier-method-labeling) · [Daru Finance](https://daru.finance/research-review/lopez-de-prado/labeling-and-cross-validation)
- 소표본 보정: [Hierarchical Beta-Binomial Shrinkage](https://metricgate.com/docs/hierarchical-beta-binomial-baseball/) · [Empirical Bayes 계산기](https://metricgate.com/docs/empirical-bayes/) · [Sorting rates using empirical Bayes](https://andrewpwheeler.com/2018/07/23/sorting-rates-using-empirical-bayes/)
- 확률 보정: [MQL5 — Probability Calibration for Financial ML](https://www.mql5.com/en/articles/21938) · [Workflow for Calibrating Predicted Probabilities](https://metricgate.com/blogs/workflow-calibrating-predicted-probabilities/) · [Kalshi — Calibration in Prediction Markets](https://kalshi.com/research/kalshi-research-calibration.pdf)
- 백테스트 과적합: [Deflated Sharpe Ratio(SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551) · [Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) · [ML4T 정리](https://stefan-jansen.github.io/machine-learning-for-trading/08_ml4t_workflow/01_multiple_testing/)
- 단기 반전: [Cox & Peterson 1994](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1994.tb04428.x) · [Cheng·Hameed·Subrahmanyam·Titman 2017](https://si-cheng.net/wp-content/uploads/2018/12/2017-JFQA-Cheng_Hameed_Subrahmanyam_Titman-Short-Term-Reversals.pdf) · [Collin-Dufresne & Daniel](https://www.kentdaniel.net/papers/unpublished/str2.pdf) · [Da·Liu·Schaumburg](https://academicweb.nd.edu/~zda/Reversal.pdf)
- 첫 도달 확률: [First Hitting Time(PUC-Rio)](http://marcoagd.usuarios.rdc.puc-rio.br/hittingt.html) · [Reflection Principle](https://riskhub.org/blogs/reflection-principle-for-brownian-motion)
