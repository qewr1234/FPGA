# Q1 Bank-Permutation 재배열 모델 배포

- [**재배열 정수 CNN 모델 ZIP (GitHub 파일)**](./q1_bank_reordered_export_20261018.zip)
- [고정 채널 순열 정의](../bank_export_perm.json)
- [ZIP 재생성 Python 스크립트](../../../scripts/q1_package_reordered_export.py)
- [보드 A/B 검증 절차](../BANK_BOARD_AB_PROTOCOL_20261018_KO.md)

위 ZIP은 GitHub 저장소의 기존 `denoise/export/dn_d10_c32_us_fx_qat` 원본 가중치와 고정된 8개 레이어의 채널 순열로 다시 생성되었습니다. 원본 Export는 수정하지 않았습니다. 바이너리 ZIP은 GitHub Actions가 생성·검사해 이 위치에 커밋합니다.

## Windows FPGA PC 설치

1. ZIP을 GitHub에서 다운로드.
2. 압축 해제한 `dn_d10_c32_us_fx_qat` 폴더를 `C:\fpga\FPGA\build\q1_reviewer_export\` 아래에 배치.
3. GPU/CPU 단독 사전 확인:

```bat
cd /d C:\fpga\FPGA
python scripts\run_denoise.py --model dn_d10_c32_us_fx_qat --export-dir build\q1_reviewer_export\dn_d10_c32_us_fx_qat --emulate --set Set12 --images 05.png --out build\q1_bank_emulate_only
```

**주의:** 이전 BSD68 68/68 원본 대비 정수 영상 출력 일치, 예정 코어 사이클 개선은 GPU/CPU 분석 결과입니다. 새 모델의 물리 FPGA 구동, 전체 처리시간, 전력 및 Smart ZYNQ SL PS/DDR/MIO 호환은 별도 실측이 필요합니다. 적합성 확인 전 기존 ZedBoard 빌드를 보드에 내려받지 마세요.
