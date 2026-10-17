# W4 채널 순열 보드 A/B 실험 절차 (2026-10-18)

**현재 증거:** Set12 01/05 및 BSD68 68장 기준 GPU 정수 CNN 최종 8비트 출력 불일치 0, 고정 순열 W=4 분석 계수에서 BSD68 전체 68/68 개선, conv2~9 합계 −8.7838%. **물리 FPGA 실측 아님.**

## 중요: 보드 프리셋 경고

기존 W4 자료의 Vivado `zed_v4_p16_t4_w4_*` 빌드/PS7 설정은 ZedBoard 프리셋에서 왔을 수 있습니다. XC7Z020 부품 번호만 일치한다고 Smart ZYNQ SL DDR/MIO/전원·클럭 설정이 호환되는 것은 아닙니다.

**실제 Smart ZYNQ SL 제조사/제작자 제공 PS DDR/MIO 설정, 비트스트림, XSDB 연결 절차를 먼저 검증하세요. 불확실하면 아래 FPGA 프로그래밍 명령은 실행하지 마세요.**

## 0. 2026-10-18 추가: GitHub 배포형 안전 실행기

FPGA PC에서 아래 순서로 진행합니다. 첫 명령은 압축파일 무결성과 원본/순열 모델을 확인하고 `build/q1_reviewer_export/dn_d10_c32_us_fx_qat`에 준비할 뿐, **FPGA/JTAG 프로그래밍을 절대 하지 않습니다**.

```bat
cd /d C:\fpga\FPGA
git status
git pull origin main
RUN_FPGA_Q1_BANK_PREFLIGHT.cmd
```

실제 Smart ZYNQ SL 보드에 적합한 PS DDR/MIO 설정과 W=4 비트스트림을 확인한 후, **FPGA PC에서만**, 명시적인 경로와 별도의 run-id를 사용합니다.

```bat
RUN_FPGA_Q1_BANK_AB.cmd "C:\Xilinx\Vivado\2026.1\bin\xsdb.bat" "C:\fpga\FPGA\build\APPROVED_SMART_ZYNQ_SL_W4" trial_01 1
```

위의 두 번째 경로는 **예시 자리표시자**입니다. 실제 검증된 빌드 경로로 교체하지 않았다면 실행하지 마세요. 사용자 확인 문자열을 입력하기 전까지 보드 실행이 시작되지 않습니다. 이전 `zed_v4_*` 또는 `ZedBoard` 빌드는 거부합니다. 비교 결과는 `build/q1_bank_fpga_runs/trial_01/pair_01/comparison.json`에 저장되고, 기존 결과를 덮어쓰지 않습니다.

**주의:** 확인 문자열은 물리적 핀 설정의 자동 검증이 아니라 사용자가 보드 매뉴얼/설계와 대조했다는 선언입니다. 호환을 확신하지 못하면 첫 번째 사전 점검까지만 수행해야 합니다.

## 1. GPU PC에서 학습/최적화 없이 후보 보존

기존 `build/q1_reviewer_export/dn_d10_c32_us_fx_qat/` 폴더 안에 `manifest.json`, `int_eval.json`, `permutation_manifest.json`, `conv1_config.bin` ~ `conv10_config.bin` 가 있어야 합니다.

위 폴더를 **그대로** FPGA PC의 `C:\fpga\FPGA\build\q1_reviewer_export\dn_d10_c32_us_fx_qat\`로 복사하세요. 또는 제공된 `q1_bank_reordered_export_20261018.zip`을 `build\q1_reviewer_export` 위치에 압축 해제하세요.

모델/가중치를 GitHub 원본 `denoise/export/dn_d10_c32_us_fx_qat`에 덮어쓰면 원본 대비가 불가능해지므로 **절대 덮어쓰지 마세요**.

## 2. FPGA PC에서 read-only 사전 점검 (보드 프로그래밍 없음)

```bat
cd /d C:\fpga\FPGA
git status
git pull origin main
dir build\q1_reviewer_export\dn_d10_c32_us_fx_qat
python scripts\run_denoise.py --model dn_d10_c32_us_fx_qat --export-dir build\q1_reviewer_export\dn_d10_c32_us_fx_qat --emulate --set Set12 --images 05.png --out build\q1_bank_emulate_only
```

`--export-dir`는 2026-10-18에 추가된 **명시적 Export 입력 경로** 옵션입니다. 기존 `--model`만 쓰면 원본 Export를 읽습니다. 이 단계에서는 프로그램이 CPU에서 실행되고 FPGA를 프로그래밍하지 않습니다.

## 3. FPGA에 맞게 검증된 비트스트림을 명시적으로 지정한 뒤 실측

다음 명령은 **호환되는 보드 전용 W=4 bitstream의 정상 실행 및 PS DDR/MIO 설정을 이미 검증한 경우에만 사용**합니다. 아래 `<APPROVED_W4_BUILD>` 와 `<YOUR_XSDB_PATH>`는 실제 경로로 바꿔야 하며 어떤 디폴트 빌드도 자동 선택하지 않습니다.

원본:

```bat
python scripts\run_denoise.py --model dn_d10_c32_us_fx_qat --xsdb "<YOUR_XSDB_PATH>" --build "<APPROVED_W4_BUILD>" --w4 --fclk 50 --mode 1 --set Set12 --images 05.png --tile 65536 --out build\q1_bank_board_baseline --board-dir build\q1_bank_board_baseline_io
```

순열 후보:

```bat
python scripts\run_denoise.py --model dn_d10_c32_us_fx_qat --export-dir build\q1_reviewer_export\dn_d10_c32_us_fx_qat --xsdb "<YOUR_XSDB_PATH>" --build "<APPROVED_W4_BUILD>" --w4 --fclk 50 --mode 1 --set Set12 --images 05.png --tile 65536 --out build\q1_bank_board_permuted --board-dir build\q1_bank_board_permuted_io
```

동일한 이미지·노이즈 seed(스크립트 기본 0)·비트스트림·sparse mode=1·클럭 50MHz·분할 크기 65536을 유지하고 비교하세요. 원본과 순열 후보를 번갈아 최소 3회 재측정하여 반복성 평가. **반복 실행 시에도 서로 다른 `--out` 경로를 지정하여 이전 결과를 덮어쓰지 않으세요.**

## 4. 자동으로 두 보드 결과의 일치 조건을 검사하고 결과 비교

```bat
python scripts\q1_board_ab_compare.py --baseline build\q1_bank_board_baseline\report.json --permuted build\q1_bank_board_permuted\report.json --out build\q1_bank_board_ab_compare.json
```

스크립트는 동일 모델명, Set, sigma, 입력 이미지 크기, 10레이어 형상, W=4 Core ID, 실제 PL clock, mode=1, 모든 레이어의 bit-exact mismatch=0, output PSNR 일치 등을 검사합니다. 조건이 다르면 결과를 합치지 않고 에러를 발생시킵니다.

## 5. 측정 후 기대값과 기각 기준

- 05.png는 이미 분석했던 이미지이므로 **빠른 재현 확인용**, 논문용 핵심 일반화 증거는 아니며, BSD68 여러 이미지의 실제 보드 런을 독립적으로 확보해야 함.
- 이전 05.png 분석의 전체 코어 사이클 −7.02%는 **조건부 예측**일 뿐. 실측 감소가 음수거나 0에 가까우면 모델 오류, bank scheduling, load/compute overlap, DMA, config I/O를 먼저 진단.
- `IN_STALL`과 `OUT_STALL`이 기존/순열 간 달라진다면 사이클 차이를 순수 계산 이득이라고 단정하지 않을 것.
- 비트스트림을 동일하게 유지하고 가중치·activation 채널 배치만 변경하므로 RTL 하드웨어 자원은 원칙적으로 동일. **하지만 PS/JTAG 호스트 벽시계 시간 전체도 개선된다고 주장하지 마세요.**
- 선행연구의 일반 채널 순열, 가장자리 희소량, bank balance 기법과 차이를 입증하지 않으면 Q1 신규성 주장 금지.

**이번 A/B는 core cycle의 실재성을 판정하는 Gate입니다. 논문 완성을 의미하지 않습니다.**
