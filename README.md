# Shopify Product Classifier

A Django-based backend for classifying Shopify products using machine learning. The service ingests product data from Shopify stores, applies taxonomy-based classification, and exposes a REST API for managing products, categories, and classification results.

## Local Setup

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
