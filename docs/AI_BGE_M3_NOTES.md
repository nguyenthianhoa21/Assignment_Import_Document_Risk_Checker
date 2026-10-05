# AI trong Import Document Risk Checker - BGE-M3 (offline)

## 1. Vai tro cua AI trong he thong

| Tang | File py | Vai tro |
|---|---|---|
| Doc file PDF | `app/services/pdf_parser.py` | OCR/text-layer -> `raw_text` (khong goi AI) |
| Trich xuat du lieu | `app/services/openrouter_extractor.py` | AI-first: goi OpenRouter (`qwen/qwen3.8-27b:free`), tra `ExtractedDocument` JSON. Loi 429/timeout/parse -> fallback `extract_document_offline()` (regex deterministic) |
| Doi chieu 3 chung tu | `app/services/validation_engine.py` + `app/services/bge_matcher.py` | Rule deterministic cho so hoc + **BGE-M3** cho chuoi van ban (ten phap nhan, dia chi, ten cang) |

Nguyen tac: LLM chi dung de *trich xuat*, khong dung de *quyet dinh*. Moi quyet dinh bao loi do rule engine chay bang Python thuan.

## 2. BGE-M3 la gi va vi sao dung offline

`BAAI/bge-m3` la mo hinh embedding da ngon ngu da ngon (dense vector 1024 chieu), hoat dong 100% offline qua `sentence-transformers` + `torch`. Khong goi OpenAI hay API trả phí nao.

Config trong `app/config.py` va `.env`:

```bash
BGE_MODEL_ENABLED=true
BGE_MODEL_NAME=BAAI/bge-m3
BGE_SIMILARITY_THRESHOLD=0.995
```

## 3. `BGEMatcher` - 4 buoc kiem tra

`app/services/bge_matcher.py`, class `BGEMatcher` dung lazy singleton (load model 1 lan, co khoa `threading.Lock`, tu detect CUDA, mac dinh CPU).

Hàm chinh `BGEMatcher.compare(text1, text2) -> BGECompareResult(is_consistent, score, diff_tokens)`:

1. **Fast-path**: chuoi tho bang nhau -> `is_consistent=True, score=1.0`, khong co token sai.
2. **Tokenize & clean**: chuan hoa chu hoa, tach token bang regex `[A-Z0-9]+` (bo dau cham) -> danh sach token chuan xac.
3. **BGE-M3 encoding**: encode 2 chuoi, tinh cosine similarity giua 2 vector.
4. **Quyet dinh strict**: `is_consistent = len(diff_tokens) == 0 AND score >= 0.995`.

Nghia la: chi mot khiuat tu (FOOD vs FOODS) hoac mot chu sai (CAT LAI vs CAT LAL) la da du de bao loi, du diem embedding co cao.

**Fallback**: neu thieu `sentence-transformers`/`torch`, chua tai duoc trong so, hay het RAM, matcher tu chuyen sang so sanh token deterministic (`_strict_from_tokens`) va ghi log - server khong bao gi crash.

## 4. Ba rule nao dung BGE-M3

| Rule | So sanh | Severity | Vi du sai biet |
|---|---|---|---|
| `RULE_CONSIGNEE_NAME_SIMILARITY` (R8) | Core name giua Invoice / P/L / B/L (da bo hau to phap ly) | MEDIUM | `GREENFIELD FOOD VIETNAM` vs `GREENFIELD FOODS VIETNAM` |
| `RULE_ADDRESS_SIMILARITY` (R9) | Dia chi consignee giua cac chung tu | MEDIUM | Sai so nha / ten duong |
| `RULE_PLACE_OF_DELIVERY_TYPO` (R10) | `place_of_delivery` / `port_of_discharge` voi `CAT LAI` chuan | MEDIUM | `ECAT LAI`, `CAT LAL` |

`score` va `diff_tokens` duoc ghi vao `reason` + `evidence_snippet` de canh bao co bang chung.

## 5. Cac rule khac (khong dung AI)

`app/services/validation_engine.py` kiem tra bang Python thuan: `RULE_INVOICE_REF_MISMATCH` (IV-2026-1008 vs IV-2026-100B), `RULE_GROSS_WEIGHT_MISMATCH` (231.000 vs 232.000 KG), `RULE_CONTAINER_ID_MISMATCH` (OOLU7654321 vs OOLU7654327), `RULE_DATE_CHRONOLOGY`, `RULE_MISSING_DOCUMENT`...

## 6. Chuoi bao ve khi khong co AI

```
raw_text -> [OpenRouter] -> JSON -> ExtractedDocument
                |
                +-- 429 / timeout / JSON bad -> extract_document_offline() (regex)
```

Het ha nang thi he thong van tra ve du lieu, chi la du lieu lay bang regex. Backend khong dung Gemini/OpenAI key.

## 7. Chay test

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q
```

Test mock HTTP nen chay offline. Neu may thieu RAM, dat `BGE_MODEL_ENABLED=false` de bo qua tai model.
