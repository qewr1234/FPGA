# Bank-aware 채널 순열: 1차 실험 결과 및 적대적 검증 판단 (2026-10-18)

## 관찰한 자료

- 사용자 제공 `report.json`, `bitexact_report.json`, INT8 config 10개 + 정수 Export manifest 및 `permutation_manifest.json`을 대조 분석.
- 기존 FPGA 기준은 `denoise/board_runs/dn_d10_c32_us_fx_qat_05_w4.json`: 256×256, Set12 05.png, sigma25, 50MHz, W=4, 13,289,042 cycles, 모두 bit-exact.
- 이번 보고서는 새 보드 측정이 아니라 고정한 입력 활성값의 bank load를 이용한 **analytical per-window core-cycle prediction**.

## 결과 요약

| 평가 | 기존 | 순열 최적화/조건부 예측 |
|---|---:|---:|
| Conv2~9 sparse core coefficient cycles | 11,420,680 | 10,487,498 |
| 코어 coefficient 절감 | - | 933,182 (-8.171% of selected layers) |
| 전체 CNN 포함(기존 실측에 절감량을 반영한 조건부 계산) | 13,289,042 | ~12,355,860 (-7.022%) |
| core-only @ 50MHz | 265.78084ms | ~247.1172ms (-18.664ms) |
| 단순 평균 density-sort Conv2~9 | 10,946,907 | greedy proposal 10,487,498 |

각 Conv2~Conv9의 테스트 이미지 05.png에서 측정 모델의 예상 개선율: `7.53871%, 5.05331%, 9.44368%, 11.21929%, 6.86313%, 6.11576%, 5.91732%, 12.58477%`.

Conv2~9 모든 레이어에서 density-sort 및 그 레이어에 대해 조사한 20개 random-bank baseline 중 가장 성능이 좋았던 구성보다 낮은 예상 cycle을 얻음.

CPU 리포트는 Set12 01.png와 05.png에 대해 **최종 픽셀 불일치 0건**. 제공된 10개 config의 파일 길이와 INT8 weight 범위가 Manifest와 일치하며, 8개 레이어 간 channel permutation order도 보고서와 일치.

## 주의사항

1. **전체 7.02%는 FPGA 실측이 아니다.** 기존 core 측정(13,289,042)에서 새 후보의 예상 절감량만 차감한 조건부 분석. Fill/drain/DDR/DMA/PS overhead, latency confidence interval 없음.
2. **데이터 누출/과소평가 위험:** 최적화는 Set12 01.png 한 장(2,048 windows)만 보고 수행, 평가도 Set12 05.png 한 장. 05.png는 기존 W=4 개발 중 이미 여러 번 본 이미지이므로 ‘완전히 미개봉 테스트’가 아님.
3. **선행기법 위험:** 채널 순열로 다음 레이어 가중치를 함께 재배열하는 기술은 선행연구 있음. 이 성능 결과가 그대로 새로운 알고리즘의 학술 신규성을 의미하지 않음.
4. **품질 한계:** 두 장에서 원래 출력과 픽셀 단위 동일(PSNR 손실 없음)이지만 80장 전체 미검증. 구조적 순열 동치가 유지되는지 출력/가중치 대응을 추가 검증해야 함.
5. **범위 한계:** 현재 한 모델 `dn_d10_c32_us_fx_qat`, 채널 32, W=4, sigma25, 50MHz 코어 모델뿐. Maxout, wider CNN, W1, bank-width 변화, 실제 PS 제어 포함 전체 시간은 미확인.
6. **신규성:** 아직 Q1에 제출 가능한 독립된 contribution으로 판정 불가.

## GPU PC 후속 검증 (고정 permutation; 재최적화 금지)

```bat
cd /d C:\fpga\FPGA
git status
git pull origin main
RUN_GPU_Q1_HOLDOUT.cmd
```

입력: `build/q1_reviewer_bank/report.json`; 모델은 기존 정수 Export. 재배열 순열을 다시 학습·탐색하지 않음.

출력: `build/q1_reviewer_holdout/report.json` 및 `per_image.csv`. BSD68 68장을 지정 시드와 sigma25로 평가하며, 원래 정수 `int_eval.json`에 맞는 PSNR을 확인하고 고정 순열과 원래 순열의 **core coefficient cycles만** 비교.

차이의 image-bootstrap interval은 이미지 구성의 민감도 진단일 뿐 다중 난수 시드·모델 선정 전 과정의 CI는 아님.

### 연구상 Go/No-Go 권고

- **Gate H1 (정확성):** 원본 vs 재배열 Export의 전체 영상 픽셀 0 mismatch를 더 많은 BSD68/Set12 영상에 확인. Fail이면 중단.
- **Gate H2 (일반화):** 고정된 순열로 BSD68에서 다수 이미지 개선, 전체 cycle coefficient 절감의 방향 유지 및 기각 기준 선등록. 개선이 사라지면 순열 연구 기각.
- **Gate H3 (보드):** 같은 bitstream/fclk, 동일 이미지, 원본/재배열 모델의 보드 코어 사이클 비교, `in_stall/out_stall` 포함. 예정된 개선의 대부분이 재현되어야 함.
- **Gate H4 (논문):** 랜덤/밀도 정렬/더 강한 bank-load balancing 및 공동 탐색 문헌에 공정 비교, 모델/시그마/포트/뱅크 제약 변동 일반화.
- **Gate H5 (제품 수준):** 실제 end-to-end FPGA PS+DMA+PL 전체 시간, 전력, LUT, BRAM, 클럭 closure를 제출 전에 확보.

현재 안전한 표현은 **‘손실 없는 QAT 채널 재배열이 기존 W4 정수 CNN core의 분포 기반 cycle coefficient를 약 7% 줄일 수 있음을 단일 이미지에서 예측했다’**임. **‘FPGA 7% 가속을 달성했다’라고 작성하면 안 됨.**
