# Architecture Decision Records

## ADR 1: Why MariaDB (MySQL) over PostgreSQL?

**Decision:** Use MariaDB/MySQL as the production database.

**Rationale:** Shopify's own stack historically uses MySQL, and the project's taxonomy data model (hierarchical categories with string paths) does not benefit from PostgreSQL-specific features like JSONB columns or array types. MySQL is widely available on cloud platforms and has excellent Django support via `mysqlclient`. The simpler operational footprint matters more than PostgreSQL's advanced features for this use case.

## ADR 2: Why Celery + Redis over a simpler synchronous approach?

**Decision:** Use Celery with a Redis broker for asynchronous classification instead of processing inline in the API request.

**Rationale:** A single product classification involves an LLM API call that takes 2-10 seconds. Processing synchronously would make the import endpoint unusable for batches (a 100-product import would take 3-15 minutes blocking the HTTP connection). Celery allows the import to return immediately while classification runs in the background. The thread pool within each Celery task provides additional concurrency (configurable, default 5 concurrent LLM calls per batch) without needing complex async code. Redis was chosen as the broker because it's already needed for taxonomy caching in production.

## ADR 3: Why two-stage narrow-then-classify instead of single-pass?

**Decision:** Use a keyword-overlap narrowing step (candidate_finder) to select ~15 candidate categories before sending to the LLM, rather than sending the entire taxonomy in a single prompt.

**Rationale:** Shopify's taxonomy contains thousands of categories. Sending all of them in an LLM prompt would exceed token limits, increase latency dramatically, and degrade classification accuracy (LLMs perform better with focused choices). The keyword-overlap scoring is fast (pure Python, no DB queries after cache warm) and filters the taxonomy to a manageable set. The LLM then makes the final decision from this narrowed set. This separation also makes the candidate scoring algorithm independently testable and replaceable — the module is explicitly designed as an extension point for future embedding-based search.

## ADR 4: Why thread pool concurrency inside Celery instead of Celery's own concurrency?

**Decision:** Use Python's `concurrent.futures.ThreadPoolExecutor` inside a single Celery task rather than relying on Celery's worker concurrency (prefork/pool).

**Rationale:** The classification pipeline is I/O-bound (LLM API calls), not CPU-bound. Using Celery's prefork concurrency would spawn a separate process per task, each with its own database connection and memory overhead. A thread pool within a single task allows sharing a single process and database connection while still processing multiple products concurrently. The thread pool size is configurable (`CLASSIFICATION_CONCURRENCY_LIMIT`) to match the AI provider's rate limits. Failed products are handled per-thread without affecting others.

## ADR 5: Why LocMemCache in dev and Redis in production for taxonomy?

**Decision:** Use Django's LocMemCache for taxonomy caching in development and Redis in production.

**Rationale:** Taxonomy data changes rarely (typically only during explicit `load_taxonomy` runs) and is read on every classification. Caching eliminates repeated DB queries during batch processing. LocMemCache requires zero setup for developers (it just works within the Django process) while Redis provides the shared, persistent cache needed in production where multiple Celery workers may be running. The cache is invalidated after successful `load_taxonomy` runs to keep data consistent.

## ADR 6: Why SQLite in dev and MariaDB in production?

**Decision:** Use SQLite for local development (dev settings), MariaDB for production.

**Rationale:** SQLite requires no database server installation — developers can clone the repo and run the full test suite with zero infrastructure. The dev settings override the MariaDB configuration to SQLite automatically. Production uses MariaDB for its concurrent write support, data integrity guarantees, and compatibility with MySQL tooling. CI also uses SQLite, keeping the test environment uniform and fast.
