# GPU PC에서 수행할 전체 FPGA CNN 최적화 연구 실험

**기준 시점:** 2026-10-18. **마감:** 2026-10-19.

이 패키지는 의도적으로 GPU에서 가능한 과학적 검증 범위를 넓혔습니다. 전체 연산을 실제 하드웨어 속도와 혼동하지 않습니다. 원본 INT8/QAT 모델을 변경하거나 학습을 다시 하지 않으며, 원본 FPGA RTL/비트스트림을 건드리지 않습니다.

## 실행 순서

Windows RTX 4060 Ti PC, 저장소 `C:\fpga\FPGA`:

```bat
cd /d C:\fpga\FPGA
git status
git pull origin main

RUN_GPU_Q1_SMOKE.cmd
RUN_GPU_Q1_ALL.cmd
```

git status에서 기존 변경사항이 표시되면 먼저 보존하세요. `RUN_GPU_Q1_SMOKE.cmd`는 1~2장으로 **코드 경로와 모델 로더를 미리 확인**하는 용도이고 **본 실험 결과가 아닙니다**. `RUN_GPU_Q1_ALL.cmd`은 풀실험입니다. 실행을 중단해도 동일 명령으로 다시 시작할 수 있게 CSV 진행상황을 저장합니다. **같은 결과 폴더에 다른 인자들을 섞으면 거부**합니다.

## 전체 수행 항목

| 구분 | 대상 | 실험 | 기본 설정 |
|---|---|---|---|
| A. 채널 순열 알고리즘 비교 | ReLU QAT 32ch | identity/frozen_01/density_sort/greedy/anneal/multistart/risk-aware/20 random | BSD68 68장 × sigma15/25/50 × noise seed 0/1/2, 총 **612장-조건** |
| B. 채널 폭 일반화 | ReLU QAT 64ch | 5가지 선택법 | BSD68 68장 × 3 sigma × 2 seeds, **408장-조건** |
| C. 활성화 함수 일반화 | maxout QAT | 5가지 선택법 (가상 채널 그룹) | BSD68 68장 × 3 sigma × 2 seeds, **408장-조건** |
| D. 정수 결과 일치 스트레스 | 원본 vs 재배열된 ReLU 32ch | 완전한 8-bit 결과 전체 픽셀 비교 + 레이어별 64-window 독립 INT32 spot check | BSD68 68장 + Set12 12장 × 3 sigma × 3 seeds, **720장-조건** |
| E. 하드웨어 모드 대조 | ReLU 32ch | W1 / W4 dense 채널 순열 이득은 0이라는 이론적 대조 | 정량적 독립 RTL 실측 아님 |
| F. 결과 패키징 | 모든 JSON / CSV | 실험 완결성 검사 및 근거 보고서 생성 | 실제 결과 없으면 missing 표기 |

**A/B/C는 실제 물리 FPGA가 아니라 sparse W4 PL core의 활성값 기반 analytical cycle coefficient**를 추정합니다. D는 FPGA가 아닌 CUDA/C++/Python 계산 상의 최종 이미지 보존 검사입니다.

### 알고리즘 후보

- `frozen_01`: 이전 Set12 01.png seed42로 고정한 원본 최적화 (튜닝 금지).
- `density_sort`: Set12 01/02/03 calibration에서 비영(非零) 활성값 밀도 순으로 정렬하고 4뱅크에 순환 배치.
- `greedy`: 제한된 iteration의 bank-group swap을 목적함수 증가 없이 선택.
- `anneal`: Simulated Annealing에 의한 국소 최소값 탐색.
- `multistart_greedy`: 여러 무작위 균형 배치에서 시작해 반복 탐색하고 캘리브레이션 점수가 가장 좋은 후보 선택.
- `risk_aware_greedy`: 평균 사이클뿐 아니라 창별 상위 부하(90% 분위)를 함께 고려.
- `random_mean`: 20개의 미리 고정한 balanced random 기준 결과의 평균.
- `random_best_reference`: **평가 이미지마다 random 후보 중 최적을 선택하므로 실제 적용 불가능한 상한**; 논문에서 deployable baseline이나 방법으로 간주 금지.

새 후보들은 **Set12 01/02/03, noise sigma25, seed0/1**만 보고 학습하고 BSD68을 보지 않습니다. 이때 CNN QAT weights는 재학습하지 않습니다. `frozen_01`은 기존 Set12 01.png 단일 예제에서 선택된 설정입니다.

### 산출물 (모두 GPU PC 로컬 build 아래)

- `build/q1_gpu_deadline_full/summary.json`
- `build/q1_gpu_deadline_full/per_condition.csv`
- `build/q1_gpu_deadline_full/per_image_methods.csv`
- `build/q1_gpu_deadline_full/calibration.csv`
- `build/q1_gpu_deadline_full/method_config.json` (**각 대조군 채널 매핑**)
- `build/q1_gpu_deadline_full/export_greedy.json` 등 (**추가 Export 후보에 사용 가능**)
- `build/q1_gpu_architectures/dn_d10_c64_us_es_qat/summary.json`
- `build/q1_gpu_architectures/dn_d10_c32_us_mo_fx_qat/summary.json`
- `build/q1_gpu_bitexact_stress/summary.json`
- `build/q1_gpu_deadline_final/EVIDENCE_REPORT_KO.md`
- `build/q1_gpu_deadline_final/experiment_status.json`

실험이 끝난 뒤 JSON/CSV/MD 결과 파일을 이 대화에 업로드하면 데이터 기반으로 적대적 리뷰어 반박, 실험 통계표 및 원고 결과 섹션을 작성할 수 있습니다.

## 검증 전 결정 사항

1. GPU에서 코어 계산 비용 감소가 좋아 보여도 **FPGA 실측 가속이라고 주장하지 않습니다.**
2. maxout은 feature map 기준 가상 그룹핑이며 실제 가중치 재배열/비트정확 보장이 없습니다. 64채널도 별도 물리 재배열 Export가 아직 없습니다.
3. Sigma15/50은 기존 sigma25 전용 QAT 모델에 다른 잡음 분포를 넣는 **강건성** 분석일 뿐 sigma별 전용 학습된 denoiser와의 공정한 화질 비교가 아닙니다.
4. 기존 CNN 자체는 Set12/BSD68를 참고하여 개발됐을 가능성이 있으므로 BSD68은 **순열 선택의 검증 데이터**이지 완전 미개봉 독립 데이터라고 과장하면 안 됩니다.
5. Random best reference는 평가 데이터에서 선택하는 불공정한 기준이고, bootstrap CI는 이미지 집합에 대한 기술적 재표집입니다.
6. RTX 4060 Ti가 하드웨어 실행을 대체할 수 없습니다. 실제 Smart ZYNQ SL bitstream 설정/DDR/MIO는 별도로 확인해야 합니다.
7. **채널 순열과 bank load balancing의 선행연구가 존재합니다.** 이번 범위는 메커니즘과 실측 가능한 재현성을 다질 뿐, 새로운 Q1급 알고리즘의 완성을 보장하지 않습니다.

## 실패 복구와 사용법

- `RUN_GPU_Q1_SMOKE.cmd`가 실패하면 즉시 로그를 보고 소스 수정. 본 실험을 시작하지 말 것.
- `RUN_GPU_Q1_ALL.cmd` 중간에 중단되었다면 그대로 재실행. 이미 저장된 각 이미지의 결과는 다시 계산하지 않음.
- GPU 메모리 부족이나 driver 문제일 때 옵션 `--device cpu`로 축소 실험할 수 있지만 기본은 자동 GPU.
- 풀실험 전에 original `build/q1_reviewer_bank/report.json` 및 candidate `build/q1_reviewer_export/dn_d10_c32_us_fx_qat/`가 존재해야 함.
- 물리 보드 실험은 별도 `RUN_FPGA_Q1_BANK_PREFLIGHT.cmd`와 명시적으로 검증된 비트스트림에서 실행.

## Q1 논문 판정

GPU 검증과 실제 FPGA 테스트는 별개. 제출 전에 최신 선행연구 대비 신규성 분석, 정량적 FPGA 측정, 계측 신뢰도·통계, 재현 코드가 필요합니다. 완료된 GPU 연구 패키지라도 단독으로 Q1급 novelty를 보장하지 않습니다.
