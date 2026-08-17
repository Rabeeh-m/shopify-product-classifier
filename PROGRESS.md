# Stage 7: Confidence Scoring & Classification Persistence — COMPLETE

Ready for Stage 8.

## Completed
- `classification/services/confidence.py` — pure function combining AI self-reported confidence with data-completeness rules: title-only cap at 50, no-description cap at 65, no-image 5-point penalty (floor 30), mutually exclusive rules
- `classification/services/persistence.py` — `save_classification()` wraps all writes in `transaction.atomic()`: creates/updates Classification row (category, confidence, alternatives, status), creates ClassificationAttribute rows with case-insensitive AttributeValue resolution or free_text_value fallback, mirrors status to Product.status
- `CLASSIFICATION_CONFIDENCE_THRESHOLD` setting (default 70): above/at threshold → product.status='done'; below → product.status='needs_review'; Classification.status always='needs_review' (no auto-approval)
- 15 confidence tests (full data, no description, title-only, no-image penalty, edge cases) — all pure, no DB
- 16 persistence tests (resolve attribute, create classification, resolve values, free text fallback, threshold mapping, idempotency, rollback on failure, missing category)
- 122 total tests passing, all linting clean
