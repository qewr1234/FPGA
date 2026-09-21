# 선행 연구 대조 및 수정 사항 (2026-09-21 2차 점검)

이 문서는 본 연구의 주장을 문헌에 대조해 다시 점검한 결과다.
1차 점검이 "비슷한 연구가 있는가"를 넓게 본 것이라면, 이번에는 DSP 게이팅 후
확정된 주장 세 가지를 각각 겨냥해 다시 찾았다.

확정된 주장:
- (A) 곱셈기 64개 등가 조건에서 두 구조의 창당 cycle 차이는 5.1%다.
- (B) 곱셈기 1개 추가 비용은 P축 138.5 LUT / 111.6 FF, T축 89.8 / 43.8이다.
- (C) 위 cycle 수치는 Zynq-7020 실측과 정확히 일치한다.

---

## 1. 가장 위험한 선행 연구 — Ma et al., FPGA 2017

Ma, Cao, Vrudhula, Seo, *"Optimizing Loop Operation and Dataflow in FPGA
Acceleration of Deep Convolutional Neural Networks"*, FPGA 2017.

FPGA CNN 가속기에서 **어느 루프 축을 펼칠 것인가**와 그에 따른 하드웨어 비용을
설계 변수 조합으로 체계적으로 탐색한 정준 논문이다. 주장 (B)의 형태 — "축을
바꾸면 곱셈기당 비용이 달라진다" — 는 이 논문이 이미 확립한 명제다.
**인용하지 않으면 리뷰에서 반드시 지적된다.**

본 연구가 남기는 증분:
1. Ma et al.은 **조밀(dense)** 합성곱을 대상으로 한다. 비영 tap을 뱅크로 나누는
   축은 희소성이 없으면 존재하지 않는다. 즉 T축은 그 설계공간에 없다.
2. Arria 10에서 DSP 기반으로 측정했다. 본 연구는 DSP를 0으로 강제한 전-fabric
   구현의 post-route LUT/FF이므로 비용 축이 다르다.
3. 목적이 다르다. Ma et al.은 처리량 최대화를, 본 연구는 곱셈기 예산 고정 하의
   대조를 목적으로 한다.

→ **조치**: 서론에서 명시 인용하고 "조밀 가속기의 루프 축 비용 분석은 확립되어
있으나, 희소 가속기에만 존재하는 tap-뱅킹 축은 그 대상에 포함되지 않는다"로
위치를 잡을 것.

## 2. 등가 자원 비교라는 프레이밍은 기여가 아니다

검색 결과 FPGA CNN 가속기에서 Throughput/DSP 같은 **자원 정규화 지표와 DSP 예산
고정 비교는 이미 표준 관행**이다. 자원 제약 하의 DSE(루프 타일링/언롤링/재배열)도
마찬가지다.

현재 초록의 첫 문장("보고되는 속도 향상은 비교 대상의 연산 자원이 서로 다를 때
의미를 잃는다")은 이 관행을 모르는 것처럼 읽힌다. 방법론 자체를 기여로 내세우면
약점이 된다.

→ **조치**: 초록 도입을 "등가 비교를 한다"가 아니라 "희소 전용 축의 post-route
비용이 비교된 적 없다"로 교체했다. (본 커밋에서 반영)

단, 본 연구에는 방어 가능한 차이가 하나 있다: Throughput/DSP는 DSP를 쓰는 설계를
전제한다. 본 구현은 DSP=0 강제의 전-fabric이므로 정규화 단위가 DSP가 아니라
**곱셈기 1개당 LUT/FF**다. 소형 디바이스에서 DSP가 이미 다른 용도로 소진된
상황을 가정하면 이 단위가 더 적절하다는 논거는 성립한다.

## 3. 정적 modulo 할당은 약점이다 — 먼저 밝혀야 한다

희소 가속기 문헌이 반복해서 지적하는 문제가 **weight load imbalance**다.
필터 채널마다 비영 가중치 분포가 달라 병렬 레인 간 부하가 어긋난다.
Multi-Bank Hash Selection(Micromachines, 2024)은 이를 뱅크 해시 선택으로 풀되,
**뱅크와 연산 유닛을 잇는 crossbar가 로직 사용량과 플로어플랜을 압박한다**고
스스로 보고한다. 또한 정적 부하 분산은 동적 활성값 희소성에 효과적이지 않다는
지적이 있다.

본 연구의 `t mod T` 할당은 정적이고 crossbar가 없다. 그래서:
- **유리한 방향**: crossbar 비용이 없으므로 면적 결과가 그들과 반대 부호로 나온
  것이 설명된다. 이것은 실제 기여다.
- **불리한 방향**: 부하 분산을 아예 포기했다. tap 분포가 치우친 계층에서는 특정
  뱅크가 병목이 되어 cycle 이득이 사라질 수 있다. 본 연구는 단일 계층
  (`features.3`)만 측정했으므로 이 경우를 배제하지 못한다.

→ **조치**: 한계 절에 이 문장을 그대로 넣을 것. 리뷰어가 먼저 말하게 두지 말 것.

## 4. 살아남는 주장

- 비영 tap 병렬 축과 출력 채널 병렬 축의 **곱셈기당 post-route LUT/FF 비용 대조**는
  검색 범위에서 명시적으로 다뤄진 사례를 찾지 못했다. 주장 (B)가 핵심이다.
- crossbar 없는 정적 뱅킹이 면적에서 유리하다는 결과는 Multi-Bank Hash Selection의
  보고와 반대 부호이고, 그 차이가 crossbar 유무로 설명된다.
- 주장 (C)의 실측 일치(cycle 7,404,123, 불일치 0, stall 0)는 재현 가능한 사실이고
  시뮬레이션만으로 끝내는 논문 대비 강점이다.

## 5. 수정 목록

1. 서론에서 Ma et al. FPGA'17과 Multi-Bank Hash Selection을 인용하고 두 축 모두에
   대해 위치를 잡을 것. (미반영 — 본문 작성 시)
2. 초록 도입부 교체. (반영 완료)
3. 한계 절에 다음 네 가지를 명시:
   - 정적 modulo 할당은 부하 분산을 하지 않으며 치우친 희소성에서 불리할 수 있다.
   - 단일 계층만 측정했다.
   - v3는 DSP-free 데이터점이 2개뿐이므로 그 기울기는 법칙이 아니라 두 점의 직선이다.
   - 등가 곱셈기 쌍(v3 P=64 대 v4 P=16,T=4)은 합성까지만 수행했고 보드 실측이 없다.
   (미반영 — 본문 작성 시)
4. "제안한다"를 쓰지 않는 현재 어조 유지. 본 연구는 대조이지 새 구조 제안이 아니다.

---

## 6. 추가 측정 — 정적 뱅킹의 부하 불균형을 수치로 (2026-09-21)

3절의 약점을 "불리할 수 있다"로 두지 않고 실제 데이터에서 재었다
(`scripts/bank_imbalance.py`, evaluation 512창, K=576, tap당 비영 비율 평균 0.569,
최소 0.106, 최대 0.979).

뱅크는 lockstep이므로 한 창은 가장 찬 뱅크만큼 걸린다. `T*max(count) / sum(count)`:

| T | 평균 불균형 | 최악 창 |
|---|---|---|
| 2 | 1.062x | 1.188x |
| 4 | 1.157x | 1.469x |
| 8 | 1.351x | 2.059x |
| 16 | 1.639x | 2.557x |

중요한 점: **이 손실은 이미 보고한 cycle 수치 안에 들어 있다.** 보드가 바로 이
데이터를 돌렸고 cycle이 시뮬레이션과 정확히 일치했기 때문이다. 즉 5.1% 차이와
곱셈기당 비용 수치는 불균형을 이미 지불한 뒤의 값이다.

그래서 한계 문장을 이렇게 쓸 수 있다 — 추측이 아니라 측정으로:

> 정적 modulo 할당은 부하 분산을 하지 않는다. 본 계층에서 그 대가는 T=4에서
> 평균 1.16배, T=8에서 1.35배이며 보고된 cycle에 이미 포함되어 있다. 다만 T가
> 커질수록 불균형이 커지므로(T=16에서 1.64배), 희소성이 더 치우친 계층이나 더
> 많은 뱅크에서는 뱅크 축의 이점이 줄어들 수 있다.

이 표는 T를 왜 4~8에서 멈췄는지도 설명한다.

---

## 7. Ma et al. FPGA'17 원문 대조 (2026-09-21)

원문 PDF는 egress 정책으로 접근 불가(dl.acm.org, arxiv.org, semanticscholar.org,
isfpga.org 모두 403). 초록 전문과 2차 문헌의 기술 서술로 대조했다.
**본문을 쓰기 전에 원문을 반드시 직접 확인할 것.**

### 확보한 초록 (요지)

> ...convolution loop optimization을 하드웨어 설계 전에 충분히 연구하지 않으면 결과
> 가속기는 data reuse를 활용하지 못하고 data movement를 효율적으로 관리하지 못한다.
> 본 연구는 다수의 설계 변수에 기반해 CNN 가속기의 설계 목표(예: 필요 메모리 접근)를
> 정량적으로 분석·최적화한다. 설계 변수 조합 탐색으로 하드웨어 비용의 trade-off를
> 체계적으로 탐색하고, 메모리 접근과 데이터 이동을 최소화하면서 자원 활용을 극대화하는
> 하드웨어 CNN 가속 dataflow를 제안한다. Altera Arria 10 GX 1150에서 VGG-16 전체를
> 구현해 645.25 GOPS, 47.97 ms를 달성했다.

언롤 설계 변수: **Pkx, Pky**(커널), **Pix/Piy, Pox/Poy**(피처맵), **Pif**(입력 채널),
**Pof**(출력 채널). 전략은 곱셈기 수가 입력 FM 수보다 많으면 Loop-3(Nif)을 완전
언롤하고 Loop-4(Nof)를 부분 언롤해 공유 피처의 재사용을 얻는 것.

### 3절에서 내가 쓴 것 중 정정할 점

**정정 1 — "등가 곱셈기 조건"은 차별점이 아니다.**
Ma et al.의 RTL 컴파일러는 명시적으로 *"under the available number of parallel
computing resources (i.e., the number of multipliers)"* 동작한다. 곱셈기 수 고정은
그들의 전제다. 2절에서 초록 프레이밍을 바꾼 것은 결과적으로 옳았고, 이제 근거가 더
강하다. **곱셈기 예산 고정을 기여로 쓰면 안 된다.**

**정정 2 — 격차가 내가 말한 것보다 좁다.**
어제 나는 "T축은 그 설계공간에 없다"고 했다. 절반만 맞다. 조밀 연산에서 tap 인덱스는
Pkx x Pky x Pif이고, tap을 언롤하는 것은 **Ma et al.의 Loop-1 + Loop-3 언롤 그
자체**다. 즉 Ma et al.은 이미 조밀 조건에서 **출력 채널 언롤(Pof) 대 tap 언롤**을
고정 곱셈기 수에서 비교하고 있다. 이것은 본 연구의 대조와 형태가 같다.

남는 실제 차이는 더 좁고, 그래서 더 정확히 써야 한다:

1. **구조가 다르다.** 조밀 언롤에서 tap 스트림은 길이가 고정이고 지연이 결정적이다.
   희소에서는 tap 스트림이 압축되어 길이가 가변이므로, `t mod T`는 *동적 스트림에
   대한 정적 해시*가 된다. 결과로 뱅크 불균형(6절: T=4에서 1.16배)과 가변 cycle이
   생긴다. 이 구조는 조밀 언롤에 존재하지 않는다.
2. **비용 지표가 다르다.** Ma et al.의 설계 목표는 **메모리 접근과 데이터 이동**이고
   자원은 DSP 활용률로 본다. 본 연구의 지표는 **DSP=0 강제 전-fabric의 곱셈기당
   post-route LUT/FF**다. 소형 디바이스에서 DSP가 소진된 경우를 겨냥한다.
3. **희소성이 없다.** Ma et al.은 조밀 VGG-16이다. 0 생략이 없으므로 불균형도, 가변
   지연도, crossbar 여부 문제도 발생하지 않는다.
4. **검증 방식이 다르다.** 그들은 최적화된 단일 설계의 처리량을 보드에서 보인다.
   본 연구는 **대조 쌍의 cycle 모델이 실측과 일치함**을 보인다.

### 이에 따른 주장 재조정

기여를 이렇게 좁혀서 쓸 것 — 넓게 쓰면 Ma et al.에 먹힌다:

> 조밀 조건에서 출력 채널 언롤과 tap 언롤의 비용 trade-off는 확립되어 있다
> [Ma et al. 2017]. 본 연구는 **희소 조건에서** 같은 대조를 수행한다. 희소에서는
> tap 스트림이 가변 길이이므로 tap 축이 정적 뱅크 해시로 구현되고, 이는 조밀
> 언롤에 없는 부하 불균형과 가변 지연을 수반한다. 그 구조의 곱셈기당 post-route
> LUT/FF 비용은 보고된 바 없다.

즉 기여는 "축을 비교했다"가 아니라 **"희소 tap 축의 실제 fabric 비용이 이것이다"**다.

---

## 8. 원문 확인 완료 (2026-09-21) — 7절을 다시 정정

FPGA'17 저자 발표 슬라이드(63p)와 TVLSI 2018 확장판(14p) 전문을 읽었다.
7절은 초록과 2차 문헌만으로 쓴 것이라 두 군데가 또 틀렸다.

### 8.1 그들의 루프 정의

| 루프 | 축 | 언롤 변수 | 언롤 시 하드웨어 |
|---|---|---|---|
| Loop-1 | 커널 창 | Pkx, Pky | **adder tree** (fan-in Pkx x Pky) + 누산기 1개 |
| Loop-2 | 입력 채널 | Pif | **adder tree** (fan-in Pif) + 누산기 1개 |
| Loop-3 | 피처맵 | Pox, Poy | 누산기 Pox x Poy개, **adder tree 없음** |
| Loop-4 | 출력 채널 | Pof | 누산기 Pof개, **adder tree 없음** |

원문: *"Pix x Piy accumulators are used to serially accumulate the multiplier
outputs and no adder tree is needed"* / *"identical to unrolling Loop-3 using
Pof multipliers and accumulators without an adder tree."*

본 연구와의 대응: **v3의 P = Pof (Loop-4)**. **v4의 T축(비영 tap 뱅킹)은
Loop-1 + Loop-2 영역**이다. 즉 본 연구는 사실상 *Loop-1/2 축 대 Loop-4 축*을
겨루고 있다.

### 8.2 정정 3 — 등가 곱셈기 축 재배분 비교는 **이미 있다**

TVLSI 12쪽에 이 문단이 있다. 결정적이다.

> Compared with [15], the unrolling variables, i.e., Pox x Poy x Pof, of VGG-16
> are set to be 7x7x64 on Arria 10 instead of 14x14x16, **where the number of
> MAC units (= 3136) are the same** and both sets of P* variables are the common
> factors of the feature/kernel map sizes **resulting in the same computation
> cycles**. ... **To reduce the data bus width and required logic, we choose
> smaller Pox x Poy in this work as 7x7 with a larger Pof as 64.**

곱셈기 3136개 고정, cycle 동일, **로직 비용이 싼 축으로 재배분**. 본 연구가 하려는
것과 방법이 같다. 따라서:

- **"등가 곱셈기에서 축을 비교했다"는 절대 기여로 쓸 수 없다.** 2절의 결론이
  여기서 확정된다.
- 다만 그들의 비교 쌍은 **Pof 대 Pox x Poy(출력채널 대 피처맵)**이고, 근거는
  데이터 라우터/버스 폭이며, **수치가 없다**(정성적 한 문단). Fig. 18의 ALM
  분해는 선택된 설계 하나에 대한 것이다.

### 8.3 그래서 실제로 남는 것 — 이전보다 명확하다

**본 연구의 결과는 Ma et al.의 권고와 반대 방향이다. 이게 이야깃거리다.**

그들은 Loop-1(커널/tap) 축 언롤을 **명시적으로 기각**한다:

> Kernel sizes (Nkx x Nky) are small - Cannot provide sufficient parallelism /
> Kernel sizes vary considerably across different conv. layers - **Workload
> imbalance and PE mapping difficulty**

그래서 Type-(D), 즉 Loop-3 + Loop-4를 택한다. 그런데 기각 사유 둘 다 희소 조건의
본 구성에는 그대로 적용되지 않는다:
- 커널이 작아 병렬성이 부족하다 → 본 연구의 tap 축은 **K=576**이다. 부족하지 않다.
- 계층마다 커널 크기가 달라 불균형 → 본 연구의 불균형은 커널 크기가 아니라 **희소
  패턴**에서 오고, 6절에서 측정했다(T=4에서 1.16배). 종류가 다른 문제다.

그리고 본 연구의 측정은 그 기각을 뒤집는다. 곱셈기당 **T축 89.8 LUT / 43.8 FF 대
P축 138.5 / 111.6**. adder tree 공유가 누산기 복제보다 싸다.

**그들 자신의 관측이 이 메커니즘을 뒷받침한다** — 경쟁이 아니라 근거로 인용할 것:

> logic elements are mainly used to implement **accumulators in MAC units**

누산기가 로직을 지배한다면, 누산기를 P개 복제하는 Loop-4 축이 adder tree 하나를
공유하는 Loop-1/2 축보다 비싼 것은 당연한 귀결이다. 본 연구는 그 귀결을 희소
조건에서 post-route로 수치화한 것이다.

### 8.4 정정 4 — 방향이 반대로 보이는 것을 반드시 밝힐 것

Ma et al.은 **Pof를 싼 축**으로 본다(Pox x Poy 대비). 본 연구는 **Pof를 비싼 축**으로
본다(tap 뱅킹 대비). 비교 대상이 다르므로 모순이 아니다. 그러나 Ma et al.을 아는
리뷰어는 모순으로 읽는다. **이 문장을 본문에 반드시 넣을 것:**

> Ma et al.은 피처맵 축 대비 출력 채널 축이 로직 면에서 유리하다고 보고한다. 본
> 연구의 비교 대상은 피처맵 축이 아니라 희소 tap 뱅킹 축이며, 그 대비에서는 출력
> 채널 축이 불리하다. 두 결과는 비교 쌍이 다르므로 상충하지 않는다.

### 8.5 희소성 — 두 논문 모두 **0회**

`spars`, `zero-skip`, `prun`, `non-zero` 전문 검색 결과 두 PDF 모두 한 건도 없다.
16-bit 고정소수점, DSP 기반 곱셈기, Stratix V / Arria 10. 조밀 전용이 확정됐다.

### 8.6 최종 기여 문장

> 조밀 가속기에서는 커널·입력채널 축 언롤이 병렬성 부족과 계층 간 커널 크기 편차로
> 기각되어 왔다 [Ma et al. 2017, 2018]. 희소 조건에서는 tap 축이 충분히 크고
> (K=576) 구조가 균일하므로 그 기각 사유가 성립하지 않는다. 본 연구는 등가 곱셈기
> 조건에서 이 축이 출력 채널 축보다 곱셈기당 LUT 35%, 플립플롭 61% 적게 든다는
> 것을 post-route로 측정하고, cycle 모델을 실제 보드에서 검증한다.

### 8.7 인용 서지

- Y. Ma, Y. Cao, S. Vrudhula, J.-s. Seo, "Optimizing Loop Operation and Dataflow
  in FPGA Acceleration of Deep Convolutional Neural Networks," FPGA 2017,
  pp. 45-54. doi:10.1145/3020078.3021736
- Y. Ma, Y. Cao, S. Vrudhula, J.-s. Seo, "Optimizing the Convolution Operation to
  Accelerate Deep Neural Networks on FPGA," IEEE TVLSI, vol. 26, no. 7,
  pp. 1354-1367, Jul. 2018. doi:10.1109/TVLSI.2018.2815603
