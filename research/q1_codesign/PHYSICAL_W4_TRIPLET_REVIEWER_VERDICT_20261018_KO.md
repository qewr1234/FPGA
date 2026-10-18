# Q1 FPGA 실제 측정: Bank-Aware Channel Permutation 3종 실측 및 리뷰어 판정

**날짜:** 2026-10-18. **근거:** 사용자가 업로드한 triplet_summary.json, triplet_summary.md, rep_01.zip. 1회차 ZIP의 103개 멤버 전체 CRC 검사 성공, 3모델 원본 report.json 및 로그·PNG·NPZ를 독립 재집계함. 2~3회차는 종합 보고서만 제공됐으며 원시 로그 ZIP은 아직 없음.

## 1. 최초 핵심 증거: 실물 W4 가속 효과

모델 dn_d10_c32_us_fx_qat, Set12 05.png, AWGN sigma25 / seed0, FPGA core ID 0x4d410303, 50MHz, W4 sparse mode=1, 동일 bitstream SHA256 11641ab391846baeb27b006440bd4b9ec19d53da9fbf8b2742bf9f9291f247a6.

| 반복 | Original Conv1-10 | Frozen Conv1-10 | Multi-start Conv1-10 | Frozen 감소율 | Multi 감소율 |
|---:|---:|---:|---:|---:|---:|
| 1 | 13,289,030 | 12,355,814 | 12,278,419 | 7.022454% | 7.604852% |
| 2 | 13,289,030 | 12,355,814 | 12,278,419 | 7.022454% | 7.604852% |
| 3 | 13,289,030 | 12,355,826 | 12,278,419 | 7.022364% | 7.604852% |

- 3회 집계: Frozen **7.0224238%** 절감; Multi-start **7.6048515%** 절감.
- 1회차 Multi-start: **1,010,611** 물리 core cycles 절감, **20.21222ms** at 50MHz, 265.78060ms → 245.56838ms, cycle-derived throughput **1.082308×**. 이것은 PS/JTAG/영상 전체 종단 지연이나 전력을 의미하지 않음.
- Multi-start vs Frozen 1회차: **77,395 cycles** 추가 절감, Frozen 대비 **0.626385%**의 추가 cycle 감소; Original 대비 개선율 간 차이는 약 **0.582398 percentage points**. 탐색 예산/학습 조건의 공정성을 입증하지 않으므로 Multi-start optimizer의 보편적 우위라고 주장하면 안 됨.
- 반복 변화: 3회차 Frozen에서만 **DMA IN_STALL=12**로 core cycle이 12 증가. Frozen의 순수 병목 계산 사이클은 3회 일치. 전체 3회 out-stall은 0.

## 2. 동일 분모 Conv2–9 실물 개선

| 반복 | Original Conv2–9 | Frozen Conv2–9 | Multi-start Conv2–9 | Frozen 절감 | Multi 절감 |
|---:|---:|---:|---:|---:|---:|
| 1 | 11,421,202 | 10,487,986 | 10,410,591 | 8.170909% | 8.848552% |
| 2 | 11,421,202 | 10,487,986 | 10,410,591 | 8.170909% | 8.848552% |
| 3 | 11,421,202 | 10,487,986 | 10,410,591 | 8.170909% | 8.848552% |

Conv1와 Conv10은 1회차에서 세 모델 동일한 cycle. 따라서 **전체 10레이어 절감률 7.605%와 최적화 대상 8레이어 절감률 8.849%는 각각 다른 분모**이며 둘 다 명시해야 한다.

### 1회차 레이어별 실제 FPGA 원본 비용 vs Multi-start

| Layer | Original cycles | Multi-start cycles | Saved cycles | Saved % |
|---|---:|---:|---:|---:|
| Conv1 | 524,305 | 524,305 | 0 | 0.0000 |
| Conv2 | 1,504,752 | 1,378,763 | 125,989 | 8.3727 |
| Conv3 | 1,435,005 | 1,344,509 | 90,496 | 6.3063 |
| Conv4 | 1,448,350 | 1,311,511 | 136,839 | 9.4479 |
| Conv5 | 1,562,936 | 1,371,900 | 191,036 | 12.2229 |
| Conv6 | 1,369,221 | 1,272,788 | 96,433 | 7.0429 |
| Conv7 | 1,375,441 | 1,281,427 | 94,014 | 6.8352 |
| Conv8 | 1,289,021 | 1,207,219 | 81,802 | 6.3461 |
| Conv9 | 1,436,476 | 1,242,474 | 194,002 | 13.5054 |
| Conv10 | 1,343,523 | 1,343,523 | 0 | 0.0000 |
| **Total** | **13,289,030** | **12,278,419** | **1,010,611** | **7.6049** |

Conv9+Conv5가 첫 반복 절감량의 **38.10%**를 제공. Conv2~9 전부 개선했지만, 기존 σ50 분석에서는 Conv7 악화도 존재했다. **모든 입력·노이즈에서 모든 층이 개선된다는 보편 주장 금지**.

## 3. 무손실 출력 및 중간 활성화의 독립 확인

- rep_01의 Original/Frozen/Multi-start 각 report.json에서 emulated=false, 10개 Conv의 FPGA oracle mismatches=0, W4 core ID와 50MHz 모두 일치: **30개 레이어 실행 통과**.
- 1회차 세 모델의 05_clean.png, 05_noisy.png, 05_denoised.png 각각 SHA256 동일. 즉 최종 denoised PNG는 **바이트 단위 동일**.
- 세 모델의 05_maps10.npz에 저장된 conv1~conv9 각 activation (32,128,128) uint8에 대해, 32개 채널별 contiguous bytes SHA256의 **multiset** 비교: 모든 **9/9 Conv**에서 Original vs Frozen 및 Original vs Multi-start 각각 일치. 전체 tensor 원본 배열 인덱스는 대부분 불일치하며, 채널 순서만 바뀐 결과와 일관적.
- 이 검사는 각 히든 레이어가 채널 순열을 제외하고 출력 정수 값을 정확히 보존한다는 강력한 케이스별 증거다. 단 다른 영상/네트워크 전부의 형식 증명을 대체하지 않음.

## 4. 결정적 실험: **같은 Set12 입력**에 대한 Bank 병목 모델과 FPGA 실측 직접 검증

기존 BSD68 전체 평균을 이 실측과 비교하지 않고, ZIP의 **실제 보드 연산에 사용된 정수 중간 활성화 파일** `rep_01/{original,frozen,multistart}/05_maps10.npz`로 모든 10개 층의 원 입력을 복구했다.

방법: 각 층에 대해 q=image (Conv1), q=이전 Conv 출력(Conv2~9), q=concat(Conv9,image) (Conv10); 3×3 zero-pad1, tap 순서 ky,kx,channel로 im2col을 복구하여 각 창 K=36,288,324 및 N=16,384를 얻는다. 4뱅크 b별 nonzero tap 수를 세고 FPGA P=16, W=4, T=4에 맞는 독립 cycle 모델을 적용한다.

    predicted_window = max(K/4+1, ceil(COUT/16)*max(1,max_b(NNZ_b)), COUT)

이번 레이어의 K는 모두 4의 배수. 세 모델 모든 10층의 복구된 `nonzero_fraction`은 실물 각 report.json의 값과 소수 오차 **0** 수준으로 일치했다. 중간 활성화 채널 multiset도 원본과 비트 일치하므로 10층 모두 세 모델 간 비영 값 **총량은 동일**하되 뱅크별 배치만 다르다.

| 모델 | 동일 물리 입력 기반 분석 cycle 합 | FPGA measured cycle 합 | 초과 오버헤드 cycle | 잔차/실제 합계 |
|---|---:|---:|---:|---:|
| Original | **13,288,456** | **13,289,030** | +574 | 0.00432% |
| Frozen | **12,355,274** | **12,355,814** | +540 | 0.00437% |
| Multi-start | **12,277,883** | **12,278,419** | +536 | 0.00437% |

세 모델 × 10층 = 30개의 실물 층별 cycle 비교에서 초과 오버헤드는 각 **17–73 cycles**이며, 스트림 초기·종료 파이프라인 비용 규모와 일치한다. 당초 분석 모델이 이런 상수 오버헤드를 제외하고 정의되었기 때문에 기대되는 차이이나, 오버헤드 발생 원인 자체는 RTL counter 별도 로그가 없으면 확정할 수 없다.

**동일 입력에 대한 절감 효과 예측:** 13,288,456 − 12,277,883 = **1,010,573 cycles**. **물리 실측 절감:** 13,289,030 − 12,278,419 = **1,010,611 cycles**. 두 절감량의 차이는 단 **38 cycles**. 이는 절감 사이클 대비 약 **0.00376%**로 모델 메커니즘과 하드웨어 반응이 매우 가깝다는 강한 근거다.

### 주목할 Bank 병목 수치 (윈도우별 최대 Bank NNZ 평균)

| Layer | Original mean max-bank | Multi-start mean max-bank | Original floor-bound windows | Multi floor-bound windows | 실제 layer 감소율 |
|---|---:|---:|---:|---:|---:|
| Conv5 | 47.5846 | **41.6027** | 2.9846% | 9.0149% | 12.2229% |
| Conv8 | 36.2156 | **31.6484** | 51.4160% | 84.9487% | 6.3461% |
| Conv9 | 43.0424 | **35.1023** | 27.8259% | 61.1511% | 13.5054% |

**인과적 해석의 한계:** 동일 출력/동일 비영 값 개수/동일 W4 RTL/동일 입력/강한 비용모델 일치는 채널 재배열로 bank issue bottleneck을 줄였다는 *기계론적 인과 근거*이다. 단 실제 소비전력 및 PS 전체 처리시간까지 인과적으로 단정하지 않는다.

## 5. GPU 추정 모델과 FPGA 실측을 혼동하지 말 것

- 기존 GPU 모델 **10.708853%** 감소는 BSD68 68장 × sigma15,25,50 × seed3 = 612조건 **Conv2~9 합산 모델** 수치.
- 현재 물리 **8.848552%**는 Set12 **단 한 장 05.png σ25 seed0**의 Conv2~9 실측. 모집단·조건이 다르므로 10.709% − 8.849%의 수치 차이를 물리 모델 편향/오차라고 단정할 수 없다.
- 기존 BSD68 sigma25 그룹 모델 Multi-start 비용 절감은 약 **9.524899%**로, 역시 입력군이 다르다. 동일 조건별 model-vs-board paired 분석이 추가로 필요.
- 반복 3회는 동일 입력 및 동일 하드웨어의 결정론적 **재현성**이지 독립 데이터셋 표본 3개가 아님. 작은 repeat SD를 이용한 신뢰구간을 입력 분포 일반화 근거로 사용하지 말 것.
- 동일 예산 Fair-budget GPU 실험에서 Multi-start 우위는 명확하지 않았다 (B400에서 Greedy 우세, B2000 +0.073 percentage points / optimizer seeds5). 본 물리 Frozen-vs-Multi 차이는 **학습/탐색예산 공정 알고리즘 비교가 아님**.

## 6. 적대적 Q1 Reviewer 판정

**입증된 강점:** 고정 W4 bitstream, 고정 물리 PL 코어, 세 다른 모델 export, INT8 기능 보존, 실제 7.6% cycle 절감, 레이어별 뱅크 대상 효과 8.85%, stall 설명 가능한 재현성, 중간 feature map 채널 순열 동치성.

**여전히 부족:** (1) 원자료가 BSD68/Set12 다수 비사용 이미지로 물리 확장되지 않음; (2) 현재 물리 모델 1종이며 타 모델/채널 폭에서 보편성 미입증; (3) 무작위 채널 순열 및 같은 search-budget Greedy, 계층별 cost ablation의 실측 또는 짝맞춘 검증 필요; (4) 선행 N:M channel permutation 및 sparse bank balancing 대비 신규성; (5) PS+DMA end-to-end wall latency/energy는 별도 측정하지 않은 상태.

**정확한 현재 논문 주장 예시:** 'We demonstrate a function-preserving offline channel-layout transformation that reduces measured W4 FPGA convolution-core cycles by 7.60% (8.85% over the eight eligible layers) on a held-out Set12 image, using an unchanged bitstream, with bit-exact outputs.' 이것은 1이미지에 대한 결과이며 전 영상/모델/실장 보편 이득을 주장하지 않음.

## 7. 다음 우선 실험

1. **rep_02.zip / rep_03.zip 또는 3모델 raw report.json 6개** 확보하여 2·3회 raw oracle/출력 이미지를 독립 감사. 현재는 rep_01.zip만 제공됨.
2. Calibration으로 사용했던 Set12 01/02/03을 피하고 **Set12 04.png, 06.png 등 미사용 영상을 여러 개 물리 측정**. 같은 W4 bitstream, A/B/C, 50MHz, seed0, 3 repeats, exact oracle, 함께 기록할 것.
3. 가능하면 BSD68 일부와 노이즈 강도 σ15/50까지 실물 확장. 현재 실행기는 기본 σ25이며 다른 σ 실험은 입력/참조/메타를 분리해 새 안전 검증이 필요.
4. 선택편향 없는 정적 채널 무작위 대조군과 equal budget Greedy를 FPGA 코어 사이클로 비교. 1개 lucky layout로 우월성을 주장하지 않음.
5. 2번째 CNN 구조/채널 폭에 채널 순열의 bit-exact FPGA export 가능성을 증명하고, 이 모델에서도 맞춤 Bank 비용 모델과 실제 출력 사이클의 재현성을 확인.

## 8. 저장 위치

GPU/FPGA Windows PC user files:
- C:\fpga\FPGA\build\q1_bank_fpga_triplet\trial_01\triplet_summary.json
- C:\fpga\FPGA\build\q1_bank_fpga_triplet\trial_01\triplet_summary.md
- C:\fpga\FPGA\build\q1_bank_fpga_triplet\trial_01\rep_01\ (raw result/logs).

GitHub after git pull origin main:
- C:\fpga\FPGA\research\q1_codesign\PHYSICAL_W4_TRIPLET_REVIEWER_VERDICT_20261018_KO.md

### 증거 파일 SHA256 (uploads)

- triplet_summary.json: cb1f7274e9fc59a467cbff3cc39a51986353921c1d8f6292c1552b2d8bceb5e2
- triplet_summary.md: c8178026b3e4fb613118e8bc8d3d5afdf24823040a76d315817f9e3094f72ce4
- rep_01.zip: 9dfb82a867a10a2c6dac43092bd9500005f44e7a10859fb465ccd75d37743d5c

보드 bitstream SHA256: 11641ab391846baeb27b006440bd4b9ec19d53da9fbf8b2742bf9f9291f247a6.
