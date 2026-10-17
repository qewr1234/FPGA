# Zynq-7020 Adaptive Denoising: 4060 Ti algorithm screen (v1)

이 폴더는 **알고리즘 타당성 검증**입니다. 현재 결과는 *PyTorch FP32 GPU* 실험이며, Zynq FPGA 속도/전력/INT8 실측 결과가 아닙니다. 기존 `denoise/`, `rtl/`, `BOARD_KO.md` 및 보드 검증 데이터는 변경하지 않습니다.

## 목표

기존 FPGA 연구에 이미 있는 Denoising CNN을 재활용해 일부 타일에서만 CNN을 실행하고, 나머지를 3x3 Gaussian으로 처리했을 때 PSNR 손실 대비 CNN crop 작업량이 실제로 감소하는지를 평가합니다. 무작위 선택은 별도의 대조군입니다. 조건부 처리 방식이 효율적이지 않으면 이를 기각하고 원래 RTL의 데이터 이동 병목 개선으로 방향을 전환합니다.

## 실행: Windows + RTX 4060 Ti

기존 저장소가 설치된 폴더에서 CMD를 엽니다.

```bat
cd /d C:\fpga\FPGA
git status
git pull origin main
RUN_ADAPTIVE_DENOISE.cmd
```

`C:\fpga\FPGA`는 예시 경로입니다. 수정된 파일이 있다면 먼저 커밋하거나 백업하고 `git pull`하세요. 처음 한 번은 `denoise/get_data.py`가 고정된 버전의 Train400/Set12/BSD68을 내려받으므로 인터넷이 필요합니다. 저장소에 포함된 `denoise/dn_d10_c32_us_mo_fx.pt`을 사용하며 새 학습은 하지 않습니다.

- Python 3.10+ 권장, `torch` (CUDA 지원), `numpy`, `Pillow` 필요.
- 이미 GPU PyTorch가 설치된 경우 다시 설치하지 마세요. `python -c "import torch; print(torch.cuda.is_available())"`로 확인 가능합니다.
- 4060 Ti 8GB/16GB 모두를 고려해 이미지 1장 단위, 필요 시 CNN tile별로 처리합니다.
- `torch.cuda.is_available()`가 False면 CPU로 처리하므로 느릴 수 있습니다.
- `denoise/get_data.py` 데이터와 `common.test_noise`를 재사용하므로 기존 σ=25, [0,1] clipping, 7-bit noisy input 조건과 같습니다.

수동 실행/확장:

```bat
python research\adaptive_denoise\smoke_test.py
python research\adaptive_denoise\screen.py --device cuda --set Set12 --sigma 25 --tile 128
python research\adaptive_denoise\screen.py --device cuda --set BSD68 --sigma 25 --tile 128 --out research\adaptive_denoise\runs\bsd68_s25
```

## 비교 설계

- **Full CNN:** 동일한 원본 float 체크포인트의 전체 이미지 추론.
- **Fast:** 별도 학습하지 않은 3x3 Gaussian 분리형 필터.
- **Adaptive:** Noisy 영상의 `texture`(인접 픽셀 차이) 또는 `residual`(noisy-Gaussian 차이) 점수 상위 타일에만 CNN 추론.
- **Random:** 동일한 타일 예산을 무작위 선택. 동일 종자 고정.
- **Budget:** 0, .25, .5, .75, 1.0 (타일 **개수 기준**). `selected_area`는 실제 픽셀 면적 비율.
- **Halo:** 각 타일의 CNN 문맥 확보를 위해 receptive field만큼 주변 픽셀을 추가 추론하며, pixel-unshuffle 모델은 전체 영상 위상 정렬. 선택적 CNN 타일의 경계는 `fade` 픽셀만큼 Gaussian과 블렌드.

결과 파일은 `research/adaptive_denoise/runs/screen_v1/` 아래 생성합니다.

- `summary.csv`: 각 gate와 budget에서 평균 PSNR, full 대비 평균 PSNR 손실, 이미지 면적 대비 확장 crop 연산량 비.
- `per_image.csv`: 개별 영상 결과.
- `manifest.json`: 실행 명령, GPU/버전/체크포인트 SHA256/커밋 해시.

**중요:** `cnn_work_ratio`는 *CNN에 입력된 halo 포함 타일 픽셀 수 합 / 전체 이미지 픽셀 수*입니다. 실제 FPGA 사이클, DRAM 전송량, 에너지, 또는 처리 FPS를 뜻하지 않습니다. Float CNN 화질은 기존 정수 FPGA CNN 출력과 동일하다고 가정하지 마세요. 특히 토막 추론은 halo 중복 비용이 발생하며 25% 타일만 처리해도 계산비가 25%가 아닐 수 있습니다.

## 다음 단계 후보 판정 기준

탐색 단계에서 임시로, Full CNN 대비 평균 손실 ≤0.2 dB / `cnn_work_ratio` ≤0.75 / 동일 budget Random보다 좋음, 세 조건을 동시에 만족할 때에만 INT8 oracle/실보드 검증 대상으로 선정합니다. 이 수치는 논문 Q1의 기준이나 실측한 성능이 아닙니다. Test set에서 gate 설정을 결정했다면 별도의 홀드아웃 데이터로 최종 성능을 재검증해야 합니다.

비교할 때는 `summary.csv`, `per_image.csv`, `manifest.json`을 함께 보관하세요. 현재 시스템의 기존 RTL과 측정 기록은 `BOARD_KO.md`, `denoise/README_KO.md`에서 확인할 수 있습니다.
