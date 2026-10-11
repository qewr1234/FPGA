# 2026-10-11 잡음 제거기 novelty 탐색 메모 (자동 문헌 조사 결과)

8개 관점의 문헌 조사 → 5개 관점의 아이디어 생성(28개) → 9개로 병합 → 아이디어마다 반박자 3명
(선행 연구 / 사이클 모델 / 효과 과장) → 종합. 에이전트 42개, 도구 호출 1,618회.
인용된 숫자는 에이전트가 논문을 열어 읽은 값이지만, 논문에 넣기 전에는 원문을 다시 확인한다.

정정 (메모 본문의 오류):
- "repo export 불일치(29.23 vs 30.10)"는 오해다. `export/dn_d10_c64_us/`는 60 epoch cosine으로 학습한
  예전 B이고, 30.10 dB는 검증 기준 조기 종료로 다시 학습한 `dn_d10_c64_us_es`(아직 export 미커밋)다.
- 플래그 이름(`--unshuffle 2`, `--arch unet`, `--qat` 등)은 제안일 뿐 현재 CLI에는 없다.

---

# 최종 연구 메모: 30 dB 돌파를 위한 novelty 전략 (12일 워크숍 페이퍼)

## 1. 한 줄 결론

**추진할 것은 "코스트 모델이 뒤집는 설계 규칙"을 논문의 주장으로 삼고, 그 위에서 (i) QAT/OBS 인에이블러(아이디어 2), (ii) 2-level unshuffle U-Net 스케일 레저(아이디어 3), (iii) 이미 구현된 dilation을 쌓는 것이다.** 9개 아이디어 중 gain 반박을 받지 않은 것은 2번(QAT/OBS)과 3번(U-Net)뿐이고, 둘 다 사이클 계산이 정확히 재현됐다. 나머지는 novelty나 gain에서 반박됐다(선행 연구 Path-Restore, HAWQ-V3, N3Net, ECBSR 등이 이미 같은 연산자를 다룸). 솔직한 기대치: **G1(≤700, Set12 >30.0)은 성공 확률 30–40%, G2(≤1314, ≥30.4)는 15–25%**. 따라서 논문의 가치는 "30.4 달성"이 아니라 **"feed-bound 코어에서 측정한 bit-exact iso-cycle 설계공간 스윕"**에 두어야 하고, 이것은 결과가 음수여도 성립하는 novelty다.

## 2. 순위표

사이클은 dense mode, 검증된 모델 max(K, ⌈COUT/16⌉⌈K/4⌉) 기준. 괄호는 cost 반박자가 보드 데이터로 찾은 보정(+1 cycle/window, cycles ≥ COUT) 적용값.

| 순위 | 이름 | 사이클/px | 예상 float / 정수 이득 (dB) | 가장 가까운 선행 연구 | 반박 결과 (novelty / cost / gain) | 추천 |
|---|---|---|---|---|---|---|
| 1 | **OBS/PWL/QAT 인에이블러** (bias offset로 ReLU 무력화, host requant = 학습된 양자화기) | 0 (head residual 시 −9; 단 자체 sign-pair residual은 정수 −0.20 측정됨 → head 변경은 보류) | B-32+maxout: float −0.04..+0.08 / **정수 +0.08..+0.15** (QuickSRNet Tab.4 검증: per-channel QAT가 INT8 손실 −0.80→−0.04; PAMS 8-bit ≈0 손실). B: 정수 +0.00..+0.06 (손실이 이미 0.04) | FINN streamlining(threshold = activation), LSQ+ Eq.5(offset→bias fold), N2UQ/LCQ, MTLU, PWLU | 미반박 / 미반박(사이클 0 정확) / 미반박 — 단 novelty는 "인에이블러 절"로만 가능 | **필수** (가장 확실한 +0.1 정수) |
| 2 | **Scale ledger: 2-level unshuffle U-Net** (level-2에서 깊게, iso-width 64) | 1294 (보정 ~1303) / G1 변형 665–674 (sparse mode 측정 시 560–600) | G2 vs B: float +0.10..+0.25 / 정수 **−0.05..+0.20 (중앙 +0.08)**; G1 변형 vs B-32+maxout: 정수 −0.05..+0.15 (중앙 +0.05). 근거: FFDNet §III-C unshuffle −0.02(σ15)/+0.09(σ50); WINNet Tab.I 2-scale +0.04; MWCNN Tab.5 U-Net+learned-down 27.46 vs Haar 27.74 (학습 다운샘플이 0.3 dB 손해 → Haar init 필수) | SGN(ICCV'19, 멀티레벨 unshuffle, 폭 2배씩 증가), eCNN/ERNet App.A(+0.54 dB 입력 unshuffle), DRUNet SConv, NAFNet, Restormer | 미반박(단 SGN/eCNN 인용 필수) / 미반박(레저 정확; 레이어 수 오기 수정) / 미반박(크기 과대) | **G2 주력, G1 보조** |
| 3 | **Tap-budget trunk** (64ch × 4–5 taps, iso-cycle 선 (C_in, t)) | 658 (보정 668) / G2 1266 (보정 1277) | G1 vs B-32+maxout: float −0.17..+0.08 / 정수 **중앙 ~0.00**, P(>30.0) 15–20%. 근거: SCNet Tab.4 검증 Shift4-Cross vs Shift8 −0.02..−0.11, Shift4-Diag −0.33..−0.51(X 패턴 금지); DCLS Tab.1 5-of-49 76.5 vs 3x3 75.8(분류); iso-cycle = iso-MAC(16.4k vs 18.4k MAC/layer)이라 "폭 +1.0 dB" 분해 무효 | SCNet(2307.16140), Shift(1711.08141), SSL fiber lasso, Sparse Shift Layer, WRPN(폭=정밀도) | 미반박(좁아짐) / 미반박 / **반박** | 스윕 테이블의 데이터 포인트로만 (fixed plus 패턴, t=1,2,5) — 풀런 베팅 금지 |
| 4 | **Collapse-at-inference 재파라미터화** (ECB/SESR 분기 → INT8 행렬로 병합) | 0 | float +0.02..+0.08 / 정수 −0.06..+0.03. 근거: ECBSR Tab.3 검증 M4C16 BN-free +0.06(B100); DBB Tab.4 BN 없으면 이득 ~0; RepQ 검증 ECBSR INT8 PTQ −0.09(이득과 같은 크기); QARepVGG: identity-branch BN이 INT8 붕괴 유발 | ECBSR, SESR, RepSR, RepQ(BMVC'23), QARepVGG, OREPA | 미반박(다만 "quantized에 미보고" 주장은 거짓: ECBSR이 8-bit DSP에서 평가) / 미반박(BN 분기는 collapse-during-training 불가 → CPU 3–6×) / **반박** | 선택 (BN-free SESR형만, 3 seeds 풀런에서만 판정) |
| 5 | **Free output head** (idle 60 lanes: 12-basis blend / 3x3 aggregation) | 0 (COUT≤64) | float −0.02..+0.06 / 정수 −0.04..+0.04. 근거: Xu et al. 2019 Tab.2 single-image KPN 35.82 vs DnCNN 35.88 (동률); BPN Tab.2 fixed basis 34.66 vs predicted 36.29 (우리 것은 fixed = 최약 구성); agg head는 대수적으로 tied 5x5 linear head임 (앙상블 아님) | KPN, BPN, LAPAR, IDF(ICCV'25), Burger 2012 | 미반박(코스트 모델 역전만) / 미반박 / **반박** | 보류 (사이클 0이니 결과용 ablation 한 줄로만) |
| 6 | **Non-local taps** (host block matching → 1x1 taps) | 1266 / 698 | 정수 Set12 −0.04..+0.07 (중앙 +0.03). 근거: N3Net Tab.1 검증 hard-KNN-on-noisy k=7 Urban100 +0.10, Tab.3 Set12 +0.11/BSD68 +0.07(학습 임베딩 포함); NN3D Set12 +0.01, BSD68 −0.04; Buades 2026 Tab.2 PatchMatch 이웃 < 로컬 3x5 창 | NLNet(CVPR'17: 입력에서 매칭, 전 단계 재사용), N3Net baseline(iii), BMCNN | 미반박(단 "first" 주장 거짓) / 미반박(BM3D σ≤40은 prefilter 없음, 설명 오류) / **반박** | 버림 |
| 7 | **Reduction ratio g** (19×32→64→max at 1314; 19×16→64→max-4 at 666) | 1314 / 666–702 | Deep-32 vs B: float −0.2..+0.1 / 정수 **−0.45..−0.05**; Deep-16: 정수 −0.65..−0.15. 근거: Light CNN 검증 "input:output 비 1–2 권장"; MTLU 검증 FDnet(unshuffle)에서 MaxOut이 ReLU보다 −0.04; DNSR 30×32는 VDSR-MU 20×64보다 −0.00..−0.12 (더 싸지만 더 좋진 않음); 자체 7×16 vs 7×32 −0.38 | eCNN/ERNet(확장비×깊이를 HW 제약 하에 스캔), MFM 2/1·3/2, Maxout h1−h2 | 미반박(ERNet 인용 필수) / 미반박(단 학습비용 "1/4" 주장은 4× 오류, residual add가 비음수라 단조증가 결함) / **반박** | 버림 (g=4 포인트는 스윕 테이블용 15-epoch 1회만) |
| 8 | **Accumulator bus** (INT32 residual + multi-exit) | 0 / 702 | (a) 정수 −0.05..+0.04 (FQSR 8-bit vs 32-bit skip EDSR +0.02..+0.06); (b) 정수 **−0.30..+0.05** — 자체 sign-pair residual 모델이 정수 −0.20 Set12 / −0.12 BSD68 측정 | **HAWQ-V3 §3.3**(INT32 residual, 동일 동기), DRCN/MemNet, FQSR | **반박** / 미반박 / **반박** | 버림 |
| 9 | **Window-permutation routing** (region expert, variable K) | 666 / 538 at p_flat 0.5 (측정 p_flat 0.51–0.52) | 정수 −0.05..+0.07 (중앙 +0.01). 근거: Path-Restore Tab.4 검증 CBSD68 σ10 36.07→36.04, σ50 27.96→27.96 at −25% FLOPs; ClassSR Tab.1 texture 전용 expert +0.02; MalleConv Tab.2 grid 간 ≤0.1 | **Path-Restore**(TPAMI'21, 영역별 hard routing으로 flat 영역 저비용), **BLADE**(해시 필터뱅크 AWGN 디노이징, 정수 동기), MalleConv-1x1 | **반박** / 미반박(weight reload는 CYCLES에 0; 뱅크별 activation scale 불가능) / **반박** | 버림 (variable-K 속도 스토리는 각주로) |

## 3. 추천 조합

### 공통 전제 (먼저 확인, 각 10분–1시간)
- **repo export 불일치**: `denoise/export/dn_d10_c64_us/int_eval.json`은 Set12 29.23 정수인데 태스크는 B를 30.10이라 함. 현재 체크포인트로 재export/재평가해 기준선을 고정할 것. 이게 틀리면 아래 산술이 전부 흔들린다.
- **0.22 dB 진단**: B-32+maxout을 (float weights + 7-bit act) / (INT8 weights + float act)로 각각 평가해 손실 위치 확인. B-32 ReLU도 양자화해 "trunk bits" 가설 검증(gain 반박자: dn_d10_c64_us 한 런은 64ch인데도 −0.24/−0.28 손실 → 폭이 아니라 calibration/run 속성일 가능성).
- **보드 측정 2건**: (i) K=288, COUT=128 레이어를 dense/sparse 두 모드로 (maxout-at-level-2 주장용; CIFAR conv5는 sparse에서 591.5 cyc/window였음), (ii) K=144, COUT=64 (read-back 1.78 B/cycle, 미검증 지점).

### G1 (≤700 cyc/px, 목표 Set12 >30.0 / BSD68 >28.4)

**Arm A (저위험, 코드 변경 최소): B-32+maxout + dilation + QAT/OBS — 666 cyc/px (보정 ~676)**

| 레이어 | 입력 | K | COUT | cyc/window | cyc/px |
|---|---|---|---|---|---|
| conv1 | 4 phases, 3x3 | 36 | 64 (maxout→32) | max(36, 4·9)=36 (보정: ≥COUT → 64) | 9 (16) |
| conv2–9 | 32ch, 3x3, dilation (unshuffled grid) 1,2,3,2,1,2,1,1 | 288 | 64 (→32) | 288 | 72 ×8 = 576 |
| conv10 | 32ch + 4 noisy phases (skip 유지) | 324 | 4 | 324 | 81 |
| **합** | | | | | **666 (보정 ~676)** |

이득 산술 (정수 Set12, 기준 29.75):
- QAT + learned clip (+ 선택적 zero-point): +0.08..+0.15 [QuickSRNet Tab.4 검증; 우리 0.22 손실 중 ~0.07 잔존 가정]
- dilation: float 0..+0.08 [IRCNN 검증: 7-layer plain 28.94 → dilated 29.15 (+0.21, RF 15→33); 단 B-32 RF는 이미 42 px, DudeNet Tab.I 검증 dilation +0.001, FFDNet "RF 추가 이득 적음" → 상단 깎음]
- 합(중앙) 0.115 + 0.04 = 0.155, 서브가산 ×0.7 ≈ **+0.11 → 29.86 (범위 29.78–29.98)**, BSD68 28.68 → ~28.80 (>28.4 거의 확실). **P(Set12 >30.0) ≈ 25%.**

**Arm B (G2 코드 공유): L2-maxout-32 / UNet-674 — 665–674 dense (sparse 실측 ~560–600, 레이어 1개 추가 여유)**
아이디어 3의 G1 레저 그대로(L1a 36/COUT32 → 9; L1b 32→64mo K=288 → 72; down 1x1 over 128 unshuffled ch K=128, COUT=64 → 8; body 4×(64→128mo: 1152/16=72)+2×36; up 64→128 → 72 → shuffle→32, sum with L1b; L1c 72; out K=324 → 81 = 674). 이득: 정수 −0.05..+0.15 (중앙 +0.05) + QAT +0.1 → **~29.9**. Arm A와 30-epoch 스크린으로 비교해 하나만 풀런.

**G1 novelty 한 문장**: "COUT≤64가 공짜인 feed-bound 코어에서는 host requantizer가 곧 양자화기이므로, 학습된 per-channel 클립/zero-point(QAT)와 dilation·unshuffle 리샘플링이 사이클 0에 쌓이며, 같은 666 cyc/px에서 BM3D(29.95/28.37)를 BSD68에서 +0.4 dB 이상 앞서고 Set12에서 동급에 도달한다." (30.0 달성 여부에 의존하지 않도록 서술.)

### G2 (≤1314 cyc/px, 목표 Set12 ≥30.4)

**UNet-1294 (must-fix 반영판) — 1294 dense (보정 ~1303), 19 board runs, ~665k params, 학습 MAC ≈ B와 동일(~73k/px → ~6 h/run)**

| 레이어 | 레벨(windows/px) | K | COUT | cyc/window | cyc/px |
|---|---|---|---|---|---|
| e1 4→64 3x3 | L1 (1/4) | 36 | 64 | 36 (보정 64) | 9 (16) |
| e2, e3 64→64 3x3 (dilation 1, 2) | L1 | 576 | 64 | 576 | 144 ×2 = 288 |
| dn 2x2-s2 gather + 1x1 (**Haar init**, 4:1 학습 믹스 — "information-complete" 주장 삭제) | L2 (1/16) | 256 | 64 | max(256, 4·64)=256 | 16 |
| b1–b11 64→64 3x3 (dilation 1,2,3,2,1,2,3,2,1,1,1) | L2 | 576 | 64 | 576 | 36 ×11 = 396 |
| up 64→128 3x3 → host pixel_shuffle(2) → 32ch @L1 | L2 | 576 | 128 | max(576, 8·144)=1152 | 72 |
| r1 concat[32 + e3 64] → 64 | L1 | 864 | 64 | 864 | 216 |
| r2 64→64 | L1 | 576 | 64 | 576 | 144 |
| out 64 + 4 noisy → 4 (clean, skip head) | L1 | 612 | 4 | 612 | 153 |
| **합** | | | | | **1294 (보정 ~1303)** |

주의: r1의 K=864는 512×512에서 타일당 56.6 MB(DMA 64 MB 한계 아래) → `--tile 65536` 유지. 가중치 스트림 651 KB/image(0.8%)는 "제외" 명시. 변형: body 4개를 maxout(COUT=128, dense 72/px)으로 바꾸면 +144 → 1438 초과이므로, maxout은 ReLU/maxout 교대(sparse mode ~1.1×K)로 보드 측정 후에만.

이득 산술 (정수 Set12, 기준 B 30.10 — 재평가 후 갱신):
- U-Net(level-2 깊이 11층, RF ~124 px): float +0.10..+0.25 / 정수 +0.05..+0.20 [WINNet Tab.I 2-scale +0.04(스케일 자체), FFDNet 15×64 30.43(깊이 ceiling), MWCNN Tab.5 pooling U-Net 27.42 ≈ dilated 27.45(스케일 아닌 깊이가 이득원); eCNN App.A +0.54는 3-block 베이스 기준이라 할인]
- QAT (concat/shuffle의 새 requant 지점 포함): +0.05..+0.10 [eCNN 검증 PTQ 최대 −3.69 → QAT 후 −0.08]
- dilation(body): 0..+0.05 (미검증, RF 이미 >100)
- 재파라미터화(선택): float 0..+0.05, 정수 ~0
- 합(중앙) 0.125+0.075+0.025+0.02 = 0.245, ×0.6 ≈ **+0.15 → 30.25 (범위 30.05–30.35)**, BSD68 ~29.1. **P(≥30.4) ≈ 15–20%.** 공개된 ≤350k-param σ25 모델 최고는 WINNet 2-scale 30.47 float이므로 30.4 정수는 문헌 ceiling에 붙어 있다. 논문 목표를 "≥30.3 at ≤1314, 코스트 모델 유도"로 쓰고 30.4는 stretch로.

**G2 novelty 한 문장**: "레이어 비용이 K×4^−level×(1+[COUT>64])이고 리샘플링과 skip이 host 인덱싱인 코어에서는 GPU의 U-Net 규칙(저해상도 단계를 넓히고 얕게)이 '폭 고정(≤64), level-2에서 깊게, pooling/transposed conv 없음'으로 뒤집히며, 우리는 이 레저를 실제 보드에서 bit-exact로 검증한 첫 2-level unshuffled 디노이저와, 동일 사이클의 GPU식 배분(wide/shallow at L2) 대비 ablation을 보고한다."

## 4. 구현 계획 (12일, 16-core CPU, 2–3 풀런/일)

플래그 이름은 현재 CLI 스타일로 썼으며 실제 파서와 대조 필요.

**Day 0 (오늘, ~4 h)**
1. 기준선 재고정: `python denoise/quantize_denoise.py --ckpt <B.pt> --name dn_d10_c64_us` → int_eval.json 재생성(29.23 vs 30.10 불일치 해소). 1 h.
2. 0.22 dB 진단 스크립트(quantize_denoise.py에 `--float-weights` / `--float-acts` 스위치 추가, 레이어별 양자화 on/off). 1 h. B-32 ReLU 체크포인트 양자화. 0.5 h.
3. 보드: K=288/COUT=128 dense+sparse, K=144/COUT=64 측정 (`scripts/run_denoise.py --mode 0|1`). 1 h.
4. dilation 스크린 즉시 런치(이미 구현): 
   `python train_denoise.py --unshuffle 2 --depth 10 --channels 32 --maxout --dilation 1,2,3,2,1,2,1,1 --patch 96 --patches 64000 --epochs 30 --schedule plateau --name scr_b32mo_dil --threads 8` 와 `--dilation 1,1,1,1,1,1,1,1` 동일 패치/시드 컨트롤 (각 ~2 h, 8 threads 2개 병렬). **15-epoch 스크린은 val 변동 ~0.4 dB(screen_A_mo 로그)라 30 epoch + 동일 시드로.**

**Day 1–2: QAT/OBS (아이디어 2, 사이클 0)**
- `train_denoise.py`: `FakeQuant7` 모듈(학습 가능 per-layer scale, 선택 zero-point, STE)을 `pick()` 뒤에; INT8 per-output-channel weight fake-quant; BN fold/freeze; `--qat --init-from <ckpt> --qat-epochs 15 --lr 1e-4`. PWL은 **보류**(MTLU §4.3.4: 64ch에선 MaxOut이 더 나음; NAFNet Tab.1 비선형 선택 ≤0.03 dB) — QAT 단독이 0.08 dB 이상 남길 때만.
- `quantize_denoise.py`: `--scales-from <qat ckpt>`(percentile 탐색 우회), INT32 assert를 3항(|bq − Σwq·z + B_c| + 127Σ|wq|)으로 확장, 회귀 테스트: QAT=off + 옛 scale → 기존 int_eval.json bit-exact 재현.
- `scripts/run_cifar.py` im2col / `quantize_denoise.im2col`: zero-point 사용 시 pad 값 `np.full(z_c)` (두 구현 동시 수정).
- 런: B-32+maxout QAT 미세조정 (~2 h), B QAT (~3 h). 기대: 정수 손실 0.22 → ≤0.10.

**Day 2–4: U-Net 그래프 (아이디어 3), ~2.5일 코딩**
- `train_denoise.py`: `UNetDenoiser(c1=64, c2=64, n_body=11, skip='concat', dilation_body=...)`; down = `Conv2d(C,64,2,stride=2)` with Haar-init(= pixel_unshuffle(2)+1x1); up = `Conv2d(64,128,3)+pixel_shuffle(2)`; `pad_mult(4)`; `layer_shapes()`가 (name, K, COUT, windows_per_pixel, inputs)를 반환하고 `board_cycles_per_pixel()`이 level별 windows를 합산; `--patch 128 --scales 1.0,0.9,0.8`.
- `scripts/run_cifar.py`: `gather(q, taps)` (taps = [(dy,dx,cin)] 리스트; im2col(dilation)은 특수 케이스; 2x2-s2는 {(0,0),(0,1),(1,0),(1,1)}×C stride 2). 자기검사: 3x3 리스트 == im2col().
- `quantize_denoise.py`: `IntModel.run()`을 manifest 그래프 워크로(inputs=[{from, op: none|unshuffle2|shuffle2|concat}]); concat은 host에서 INT32 보존 후 단일 requant(두 7-bit 코드를 더하지 말 것); COUT=128 up 레이어 1회 export; calibration이 같은 그래프 따라감.
- `scripts/run_denoise.py`: manifest 그래프 순회, `manifest.json`에 `level`, `stride`, `shuffle_after`, `concat_with`, `taps` 추가; `--emulate`로 IntModel 대비 Set12 bit-exact 확인 후 보드.
- 스크린(Day 4 밤, 각 ~2.5 h, 30 epoch, 128 px): (a) UNet-1294, (b) **B를 128 px/같은 스케줄로 재학습(패치 크기 컨트롤)**, (c) UNet GPU식 배분 컨트롤(L2 wide/shallow, 동일 사이클), (d) UNet-674(G1 Arm B).
   `python train_denoise.py --arch unet --unshuffle 2 --channels 64 --body 11 --dilation 1,2,3,2,1,2,3,2,1,1,1 --patch 128 --patches 32000 --epochs 30 --schedule plateau --name scr_unet1294 --threads 8`

**Day 5–7: 풀런**
- G2 승자: `--epochs 300 --schedule plateau --patch 128 --threads 16 --name g2_unet1294` (~6–8 h, 128 px라 epoch당 픽셀 수 확인 후 `--patches` 조정), epoch 15·60에서 `quantize_denoise.py`로 중간 정수 손실 측정(concat/shuffle requant 지점 분리 보고).
- G1 승자 (Arm A 또는 B) 풀런 (~3–4 h), 2 seeds.
- 각각 QAT 미세조정 (~2–3 h).

**Day 8: 스윕 테이블 (논문의 novelty 데이터)** — 30-epoch 스크린, 동일 패치/시드, 각 ~1.5–2 h:
(t,C,L) = (9,32,10)+maxout [기존], (5,64,9) fixed plus-cross(d=1/d=2 교대, X 패턴 금지), (1,64,SCNet shift), (2,64,20), (4,16,19)+max-4 [g=4 포인트], 64×9 dense at 2× cycles(상한). `train_denoise.py --taps-pattern plus|cross --taps 5 --extent 5` (SparseTapConv, mask buffer; K=mask.sum()). 시간 부족 시 (5,64,9)와 (1,64)만.

**Day 9: 보드** — G1/G2 최종 모델 + ablation 모델들의 CYCLES, OUT_STALL(K=144/COUT=64, K=864 레이어), 호스트 wall-clock 별도 기록.
**Day 10–12: 집필.**

## 5. 논문 프레이밍

**Claim**: 윈도우당 cycles = max(K, ⌈COUT/16⌉⌈K/4⌉)인 gather-fed feed-bound 정수 코어에서는 (1) 출력폭 ≤64, (2) 커널 extent/dilation/임의 tap 패턴, (3) unshuffle/shuffle/stride-2 리샘플링, (4) skip/concat의 소비자측 외 비용, (5) host requantizer 안의 per-channel 비선형 양자화기가 모두 사이클 0이고, 스트림된 값의 수 K = t × C_in만이 비용이다. 이 "free-set law"가 GPU 설계 규칙(저해상도 단계 확폭, 큰 커널 회피, 좁고 깊은 망 회피, 재파라미터화는 배포 트릭)을 뒤집으며, 우리는 그 역전을 실제 보드에서 bit-exact로 측정한 iso-cycle 스윕으로 보고한다.

**Reversal 스토리 (각각 인용 가능한 선행 연구 대비 "우리 코어에선 공짜")**:
- SCNet/Shift: t=1만 싸고 폭은 C_in×C_out 비용 → 여기선 (C_in, t) 선 전체가 등비용.
- Restormer/NAFNet: "효율을 위해 저해상도에서 채널 증가" → 여기선 폭 상한 64, 깊이만 싼 축.
- ECBSR/SESR: 분기는 inference 비용 → 여기선 INT8 행렬이 유일 아티팩트(단, ECBSR도 8-bit DSP 평가였음을 명시).
- FINN/LSQ+: threshold·zero-point는 알려짐 → 우리 기여는 hard-wired ReLU를 bias offset로 무력화해 host가 전체 비선형을 소유한다는 공학 노트(novelty bullet 아님).

**Ablation 테이블 (반드시 생성)**:
| 행 | 사이클/px (모델 / 보드 측정) | float Set12/BSD68 | 정수 Set12/BSD68 | 정수 손실 |
|---|---|---|---|---|
| B-32+maxout (기존) | 666 | 29.97/28.92 | 29.75/28.68 | 0.22 |
| + QAT | 666 | | | |
| + dilation | 666 | | | |
| UNet-674 / L2-maxout-32 | 674 (sparse 실측) | | | |
| B (기존, 재평가) | 1314 | 30.14/29.01 | ? | ? |
| B @128px 재학습 (패치 컨트롤) | 1314 | | | |
| UNet-1294 ledger 배분 | 1294 | | | |
| UNet-1294 GPU식 배분 (동일 사이클) | ~1294 | | | |
| + QAT (+ 재파라미터화) | 1294 | | | |
| 스윕: (9,32)+mo, (5,64) plus, (1,64) shift, (2,64), (4,16) g=4, 64×9 dense@2× | 각 | | | |
| BM3D (clipped 7-bit) | — | 29.95/28.37 | | |
| 보드 측정: COUT 4 vs 60 (head, 동일 K); COUT=128 dense vs sparse | | | | |

**솔직한 한계 (반드시 서술)**:
- Host 작업은 O(C)/px이지만 0이 아님: requant, maxout, concat, shuffle, 그리고 가중치 재로드(이미지당 650 KB, CYCLES 카운터에는 0이나 wall-clock에는 포함). 보드 타이밍은 JTAG 전송 제외.
- 에너지/throughput: 50 MHz, DSP 없음, 64 LUT 곱셈기 → 절대 성능은 낮고 주장은 "사이클/px"에 한정; GPU와의 비교는 하지 않음.
- 정수 손실: 7-bit unsigned 활성화의 손실이 run마다 0.04–0.28 dB로 흔들림(dn_d10_c64_us 사례); QAT 없이는 어떤 아키텍처 이득도 삼켜질 수 있음. 모든 PSNR은 clipped 7-bit 입력 프로토콜이라 문헌 수치(unclipped)와 직접 비교 불가.
- 시드 노이즈 0.03–0.05 dB vs 기대 효과 0.1–0.2 dB → 핵심 행은 2 seeds, 이미지별 paired wins 보고.
- 데이터: Train400 380장 CPU 학습 → 깊은 모델은 undertrained(README: 60-epoch B가 7×32보다 낮았음).
- 미검증 인용은 논문에 넣기 전 원문 확인: LJDD-Net PConv, GFBS, Choi&Kim MU-D/DNSR 세부, CSConv, MTLU FDnet 수치(σ50/unshuffle-4 조건임), ReTiDe, "Beware of Aliases", PUCA 레벨 수치.

## 6. 버린 아이디어와 이유

- **Window-permutation routing**: Path-Restore(TPAMI'21)가 같은 메커니즘으로 CBSD68에서 0.00 dB at −25% FLOPs; BLADE가 해시 필터뱅크 AWGN 디노이징을 정수 동기로 이미 수행; 뱅크별 activation scale은 다음 레이어가 한 맵을 읽으므로 불가능. 남는 것은 "flat 픽셀이 싸다"는 속도 각주뿐.
- **Accumulator bus**: HAWQ-V3 §3.3이 INT32 residual을 같은 이유로 제안; 자체 sign-pair residual 모델이 정수 −0.20 Set12 실측 → multi-exit는 그 결함을 12배 쌓는 셈.
- **Non-local taps**: NLNet/N3Net baseline(iii)/BMCNN이 동일 연산자(입력에서 hard matching, 전 레이어 재사용); N3Net의 hard-KNN은 Urban100에서도 +0.10, Set12는 더 작음; 짝수 오프셋만 가능해 Barbara 주기 텍스처에 불리.
- **Reduction ratio g=4 / 19-layer deep-narrow**: Light CNN "비율 1–2 권장", MTLU FDnet에서 MaxOut < ReLU, DNSR은 "더 싸지만 더 좋지 않음"; 학습비용 주장이 4× 오류(iso-cycle = iso-MAC); 비음수 residual add는 단조증가 결함. g=4는 스윕 포인트 1개로만.
- **Free output head**: single-image에서 KPN head ≈ DnCNN(동률, Xu 2019 Tab.2); fixed basis는 BPN의 최약 구성; agg head는 tied 5x5 linear head. 사이클 0이므로 결과 섹션 ablation 한 줄로 격하.
- **PWL 활성화(아이디어 2의 PWL 부분)**: MTLU §4.3.4 "64ch에선 MaxOut이 최선", NAFNet 비선형 선택 ≤0.03 dB → QAT만 남기고 PWL은 보류.
- **Tap-budget 학습 arm(5x5 supernet + group lasso)**: CPU 2.8× 비용, 분류 증거만, iso-MAC이라 폭 이득 분해 무효 → fixed plus-cross 포인트만 스윕에 포함.
- **Residual(OBS) head로 −9 cyc/px**: 자체 측정 −0.20 dB 정수 손실 원인 미규명 → clean-output skip head 유지.
- **재파라미터화 BN-branch 버전**: collapse-during-training 불가 → CPU 3–6×; BN-free SESR형만 선택적으로, 3 seeds에서 정수 이득 확인 시에만.