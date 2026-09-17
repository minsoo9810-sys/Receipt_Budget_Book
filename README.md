# Receipt Budget Book — LayoutLMv3 최소 부분 파인튜닝

## 1. 전체 흐름

```text
영수증 이미지 업로드
  → main.py / ysz_ocr.py: PaddleOCR 실행 및 Supabase 저장
  → 사람이 ocr_raw_items.label 검수
  → create_dataset.py: 검수된 Supabase 행을 Dataset JSON으로 변환
  → validate_dataset.py: 구조·bbox·BIO 라벨 검사
  → split_dataset.py: Train / Validation / Test 분리
  → train_layoutlmv3.py: 동결 특징 추출 + Linear head 5-Fold 학습
  → predict_layoutlmv3.py: 새 ocr_raw_id의 BIO entity 예측
```

## 2. 이번 학습 방식

- `microsoft/layoutlmv3-base` backbone은 전부 동결합니다.
- backbone의 문서 특징은 처음 한 번만 계산하고 CPU RAM에 보관합니다.
- 학습되는 것은 `768 → 17 labels` 단일 Linear 출력층뿐입니다.
- 실제 학습 파라미터는 약 13,073개입니다.
- Train+Validation을 합친 개발 데이터에서 `StratifiedGroupKFold(5)`를 수행합니다.
- 층화 계산에서 과다한 `O` 라벨은 제외합니다.
- Test는 5-Fold와 최종 epoch 선정에 사용하지 않고 마지막 한 번만 평가합니다.
- Fold별 모델은 저장하지 않고 평가 JSON만 남깁니다.
- 최종 결과는 작은 `linear_head.safetensors` 하나만 저장합니다.

이 방식은 Full fine-tuning보다 학습 용량과 GPU 메모리가 훨씬 작지만, 데이터에
따라 최고 성능은 낮을 수 있습니다. 먼저 최소 Linear head 결과를 기준선으로
사용하고, 부족할 때만 상위 encoder 일부를 여는 것이 권장 순서입니다.

## 3. 파일 역할

| 파일 | 역할 |
|---|---|
| `main.py` | Storage 이미지 목록을 받아 OCR→규칙 파싱→DB 저장을 실행하는 팀 입력 진입점 |
| `database.py` | Supabase Storage와 DB 조회·삽입 기능 |
| `ysz_ocr.py` | PaddleOCR 실행 후 text, confidence, polygon bbox 생성 |
| `ocr_linebyline.py` | OCR 조각을 y축 기준의 행으로 묶음 |
| `receipt_parser.py` | 행 단위 OCR을 규칙 기반으로 상호명·날짜·품목·합계금액으로 파싱 |
| `item_y.py` | 품목 영역을 y축 행 기준으로 분석하는 보조/대안 파서 |
| `create_dataset.py` | `verified=True`이고 label이 있는 Supabase 행을 영수증 단위 Dataset으로 생성 |
| `validate_dataset.py` | 중복 ID, list 길이, bbox 범위, 빈 text, 허용 라벨 검사 |
| `inspect_dataset.py` | 정규화 bbox와 entity 라벨을 이미지 위에 그려 시각 검사 |
| `split_dataset.py` | O를 제외한 entity 분포를 고려해 Train/Validation/Test로 분리 |
| `train_layoutlmv3.py` | 최소 Linear head의 5-Fold, early stopping, 최종 학습 및 Test 평가 |
| `predict_layoutlmv3.py` | 최종 head를 불러와 Supabase `ocr_raw_id`의 BIO 라벨과 entity 후보를 출력 |
| `layoutlmv3_labels.py` | 모든 단계에서 공유하는 라벨 및 과거 라벨 별칭 정의 |

## 4. 설치

학습 환경에서는 다음 명령을 실행합니다.

```bash
python -m pip install -r requirements-training.txt
```

OCR 입력 파이프라인은 PaddleOCR와 OpenCV도 별도로 필요합니다.

## 5. 데이터 준비

```bash
python create_dataset.py
python validate_dataset.py
python split_dataset.py
```

시각 검사는 특정 영수증 ID를 지정합니다.

```bash
python inspect_dataset.py 15
```

생성 파일:

```text
data/layoutlm/
├─ dataset.json
├─ dataset_build_report.json
├─ train.json
├─ validation.json
├─ test.json
└─ split_manifest.json
```

## 6. 5-Fold 최소 부분 파인튜닝

CUDA/Colab:

```bash
python train_layoutlmv3.py \
  --mixed-precision fp16 \
  --folds 5 \
  --epochs 30 \
  --early-stopping-patience 5 \
  --feature-batch-size 2 \
  --batch-size 16
```

Intel XPU:

```bash
python train_layoutlmv3.py \
  --mixed-precision bf16 \
  --folds 5 \
  --feature-batch-size 1
```

학습이 중단되면 같은 명령을 다시 실행합니다. 완료된 Fold는
`fold_result.json`을 읽어 건너뛰며, 진행 중 Fold는 작은 `resume_state.pt`에서
재개합니다.

## 7. 최소 출력물

```text
outputs/layoutlmv3_linear_probe/
├─ fold_manifest.json
├─ cross_validation_summary.json
├─ model_info.json
├─ cv/
│  ├─ fold_1/fold_result.json
│  ├─ fold_2/fold_result.json
│  ├─ fold_3/fold_result.json
│  ├─ fold_4/fold_result.json
│  └─ fold_5/fold_result.json
└─ final_model/
   ├─ linear_head.safetensors
   └─ final_result.json
```

진행 중에만 `resume_state.pt`가 존재하며 정상 완료 후 자동 삭제됩니다. 사전학습
LayoutLMv3 본체는 Hugging Face 캐시에서 불러오므로 출력 폴더에 복제하지 않습니다.

## 8. 새 영수증 예측

```bash
python predict_layoutlmv3.py 171
```

결과는 기본적으로 다음 위치에 저장됩니다.

```text
outputs/predictions/ocr_raw_171.json
```

`entities`에는 STORE_NAME, DATE, ITEM_NAME 등의 묶인 후보가 들어가고,
`token_predictions`에는 OCR 단어별 BIO 라벨과 confidence가 들어갑니다.

## 9. 팀원의 새 이미지 입력

기존 처리 이미지를 건너뛰고 새 이미지만 처리합니다.

```bash
python main.py
```

일부만 시험하려면:

```bash
python main.py --start-index 139 --limit 3
```

이미 처리된 이미지까지 다시 넣어야 할 때만 `--force`를 사용합니다.
