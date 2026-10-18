# Q1 논문 — 실험 일괄 실행 매뉴얼 (2026-10-18)

기존 실제 보드 성공 비트스트림, 논문 데이터와 모델 가중치를 덮어쓰지 않고 GPU 검증과 추가 물리 FPGA 검증을 일괄 수행한다. **결과의 성공을 가정하거나 조작하지 않는다.**

## 1. Windows PC 사용법

프로젝트 루트의 Windows CMD:

    cd /d C:\fpga\FPGA
    git pull origin main
    RUN_Q1_ALL_EXPERIMENTS.cmd plan

GPU 선행 실험 모두 실행 또는 완료 결과 재사용 (FPGA 미접근):

    RUN_Q1_ALL_EXPERIMENTS.cmd gpu

**완전 일괄 실행** (동일하게 Canary를 통과한 물리 보드·전원·배선에서만 실행):

    RUN_Q1_ALL_EXPERIMENTS.cmd all "C:\Vivado\2026.1\Vivado\bin\xsdb.bat"

짧은 3영상 실물 검증으로 먼저 시작할 수도 있음:

    RUN_Q1_ALL_EXPERIMENTS.cmd all "C:\Vivado\2026.1\Vivado\bin\xsdb.bat" 04.png,06.png,08.png

GPU 검증이 끝난 경우 FPGA 물리 실험만:

    RUN_Q1_ALL_EXPERIMENTS.cmd fpga "C:\Vivado\2026.1\Vivado\bin\xsdb.bat"

실험 스크립트는 사용자 Windows PC에서 실제 실행해야 한다. GitHub에 코드 저장과 CI 테스트 완료는 **물리/ GPU 연구 실행 완료와 다르다**.

## 2. 자동 실행 항목

1. Joint vs Marginal coactivation objective, 동일 401회 Greedy 예산, Set12 01-03 calibration과 BSD68 68장 × sigma15/25/50 × seed0/1/2 × optimizer seed4의 독립 이미지 비교. 기존 2448조건 complete 결과를 검증 후 재사용.
2. BSD68 612조건에서 20개 random static bank layout, density-sort, Greedy, Anneal, Multi-start, Risk-aware, Frozen, Original 분석 비용 비교. 기존 q1_gpu_deadline_suite.py 사용. 평가데이터에서 선택한 random_best_reference는 배포 가능한 경쟁자 아님.
3. budget 400/800/2000, optimizer seed5개 공정 Greedy/Anneal/Multi-start 비교. q1_fair_budget.py.
4. Max-bank NNZ, feed/output-floor-limited, unattainable per-window oracle bound 정량화. q1_bank_mechanism.py.
5. 같은 검증된 W4 50MHz 물리 FPGA에 대해 미사용 Set12 04,06,07,08,09,10,11,12.png 8장의 Original/Frozen/Multi-start ×3반복: **72번 CNN 실행 ×10 Conv = 720개 레이어 로그**. 기존 05.png Canary/trial은 재실행하지 않는다.

GPU 4종의 개선은 **실제 FPGA 측정이 아닌 분석 사이클 추정**. 물리 절감률은 각 이미지에서 W4 실제 PL Core CYCLES 레지스터로 얻은 것만 사용한다. GPU 모델 결론과 FPGA core/ E2E 지연·전력 주장을 혼동하지 않는다.

## 3. 안전·중단·재실행

- 실물 실행 전 기존 canary_01/canary.json, 실제 bitstream SHA 11641ab391846baeb27b006440bd4b9ec19d53da9fbf8b2742bf9f9291f247a6, XSDB 파일을 검증한다.
- 실물 프로그래밍에 앞서 사용자가 SAME_PHYSICAL_BOARD_W4_CANARY_VERIFIED를 정확히 입력해야 한다. 비대화식 물리 플래싱은 거절한다. 승인 후 개별 이미지 전환은 자동화된다.
- 기존 완료 결과는 원시 보고서 및 매칭 설정을 검사한 뒤 재사용한다. 완료되지 않은 물리 폴더는 보존하고 _02, _03 같은 새 디렉터리에 실험한다.
- GPU suite는 기존 자체 config 검증/재시작 지원을 활용한다. 다른 config와 충돌하면 안전하게 멈춘다.
- 중간 실패 시 현재 status.json에 기록하고, 앞서 성공한 실험 데이터는 삭제하지 않는다. 반드시 오류를 수정하고 같은 명령을 다시 입력한다.
- 반복 3회는 같은 사진 3개가 아니며, 이미지는 독립 clean image 기준으로만 집계한다. 8장 평가만으로 전체 현실 데이터셋 일반화를 입증했다고 주장하지 않는다.

## 4. 출력 위치

전체 캠페인 결과는 매번 독립 폴더로 저장됨:

    C:\fpga\FPGA\build\q1_all_experiments\campaign\status.json
    C:\fpga\FPGA\build\q1_all_experiments\campaign\physical_per_image.csv
    C:\fpga\FPGA\build\q1_all_experiments\campaign\physical_summary.json
    C:\fpga\FPGA\build\q1_all_experiments\campaign\logs\...

기존 campaign이 있으면 campaign_02 등으로 안전하게 새 폴더를 잡는다. 각 물리 측정 원시 로그도:

    C:\fpga\FPGA\build\q1_bank_fpga_triplet\q1all_set12_04\rep_01\...

처럼 이미지별로 보존하며 기존 폴더가 있다면 _02를 사용한다. 실제 출력 경로는 CMD의 AUDIT DIRECTORY 메시지를 기준으로 읽는다.

## 5. 원클릭으로 아직 해결되지 않는 연구 항목

- **두 번째 CNN 구조/64채널:** 현재 채널 순열 exporter·objective 코드와 보드 비교 절차가 검증된 32채널 ReLU 사슬에 한정. 두 번째 CNN 전용 INT8 재배열, bit-exact export, W4 자원·물리 결과를 새로 구현해야 한다. 자동화 요약에서는 NOT_IMPLEMENTED로 표시한다.
- **End-to-end PS/DDR/PL 지연 및 에너지:** 기존 측정은 PL core cycles이며, 별도 정교한 통합 드라이버 계측은 없다. NOT_IMPLEMENTED로 기록하며 GPU wall_seconds/JTAG 시간을 실제 E2E 성능으로 포장하지 않는다.
- **W1/Dense 물리 대조군:** 현재는 수학적 음성 대조군이다. 실제 다른 비트스트림의 보드 적합성·Canary를 별도 확인한 뒤에만 실험 가능.
- **실제 선행기법을 같은 FPGA에 이식해 직접 비교:** 단순히 타 논문 서로 다른 FPGA 장치의 속도를 나란히 놓는 방법은 정당하지 않다.

이번 통합 실행을 한 번 완료하더라도 이 3~4개 항목까지 '모두 끝났다'고 주장해서는 안 된다. 다만 IF 2~3 논문을 위한 기존 32ch 코어 및 다수 이미지 검증의 대부분을 한 명령으로 재현 가능하다.

## 6. 결과 해석 게이트

현재까지 확정된 Set12 05.png sigma25 FPGA 실물 데이터는 Conv1~10 7.605%, Conv2~9 8.849% 사이클 절감. 독립 BSD68 Joint 10.264% vs Marginal 3.512%는 실제 보드가 아니라 GPU 분석모델 결과.

새로 얻은 04/06/... 출력의 결과값이 음수이면 음수 그대로 보고하고, 코어 ID/클럭/bit exact 검증이 실패하면 해당 데이터는 속도 향상 증거로 사용하지 않는다.

## 7. CI

GitHub Actions .github/workflows/q1_all_experiments_safety.yml은 계획 출력, Python 구문, 안전한 새 폴더 선택, 위조된 빈 물리 trial 거부 및 계산 결과 집계 테스트만 수행한다. CI가 FPGA를 프로그래밍한 것은 아니다.
