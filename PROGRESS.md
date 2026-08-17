# Stage 5: Candidate Narrowing — COMPLETE

Ready for Stage 6.

## Completed
- `classification/services/candidate_finder.py` — keyword/text-overlap scoring
- Simple English stemmer for inflection (sofas → sofa, shirts → shirt)
- Stop word filtering and token normalization
- Weighted scoring: name matches (3x) > path matches (1x), with bonus for both
- Configurable `CLASSIFICATION_CANDIDATE_LIMIT` setting (default 15)
- Accepts optional `categories` parameter to avoid DB queries per call
- 24 new tests (5 stemmer, 5 tokenize, 7 unit, 7 integration)
- 61 total tests passing, all linting clean
- Extension point documented for future embedding-based swap
