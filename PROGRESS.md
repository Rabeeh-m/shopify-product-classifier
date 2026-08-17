# Stage 6: AI-Based Classification Service — COMPLETE

Ready for Stage 7.

## Completed
- `classification/exceptions.py` — `ClassificationError`, `ClassificationParseError`, `AIClientError`, `AITimeoutError`
- `classification/services/ai_client.py` — Anthropic wrapper with 3-attempt retry, exponential backoff via SDK defaults, timeout handling
- `classification/services/classifier.py` — `_build_prompt()` builds structured prompt with candidates, `_parse_and_validate()` enforces JSON contract, `classify_product()` orchestrates
- Prompt includes: product title, description, brand, product_type, image URL; candidate categories with id/name/full_path
- Strict validation: chosen_category_id must be in candidate set, confidence 0–100, alternatives/attributes must be lists
- Retry policy: 3 attempts for timeouts, 429s, and 5xx; immediate fail on 4xx (non-429)
- `AI_MODEL_NAME` and `AI_REQUEST_TIMEOUT` settings; `ANTHROPIC_API_KEY` env var
- `anthropic>=0.40,<1.0` added to dependencies
- 30 new tests (6 prompt, 11 parse/validate, 7 classify_product, 6 retry logic)
- 91 total tests passing, all linting clean (black, isort, ruff)
