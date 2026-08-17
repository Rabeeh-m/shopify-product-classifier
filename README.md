# Shopify Product Classifier

A Django-based backend for classifying Shopify products using machine learning. The service ingests product data from Shopify stores, applies taxonomy-based classification, and exposes a REST API for managing products, categories, and classification results.

## Local Setup

### Prerequisites

- Python 3.11+
- MariaDB 10.6+ (or MySQL 8.0+)
- `libmariadb-dev` / `libmariadb-dev-compat` (for `mysqlclient`)

### Database Setup

```bash
# Create the database
mysql -u root -e "CREATE DATABASE shopify_product_classifier CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### Application Setup

```bash
# Clone the repo and enter the directory
git clone <repo-url> && cd shopify-product-classifier

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Copy environment file and fill in values
cp .env.example .env

# Run migrations
python manage.py migrate

# Start the development server
python manage.py runserver
```

Visit `http://127.0.0.1:8000/admin/` to access the Django admin.

## Loading Taxonomy Data

The `load_taxonomy` management command ingests Shopify's product taxonomy into the database.

```bash
# Load from local JSON file
python manage.py load_taxonomy --source taxonomy/fixtures/sample_taxonomy.json

# Dry run (preview without writing)
python manage.py load_taxonomy --source taxonomy/fixtures/sample_taxonomy.json --dry-run

# Load from a URL
python manage.py load_taxonomy --source https://example.com/taxonomy.json
```

### Input JSON format

```json
{
  "categories": [
    { "id": "abc", "name": "Furniture", "parent": null, "attributes": [] },
    { "id": "def", "name": "Sofas", "parent": "abc", "attributes": ["color", "material"] }
  ],
  "attributes": [
    { "id": "xyz", "name": "Color", "handle": "color", "values": ["Red", "Blue"] }
  ]
}
```

The command is idempotent — running it multiple times will not create duplicates.

## Testing

```bash
# Run the full test suite
python manage.py test

# Run with coverage
coverage run --source=classification,products,core -m django test
coverage report

# Run a specific module
python manage.py test classification.tests.test_classifier
```

### CI Checks

Every push and pull request runs:
- **Tests** with coverage (must be ≥90% on `classification/`, `products/`, `core/`)
- **Linting** — `black`, `isort`, and `ruff` must pass

CI uses SQLite for the database so no external services are required.
