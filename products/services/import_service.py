import csv
import io
import logging
import os

from django.conf import settings
from django.db import transaction
from django.utils import timezone as tz

from products.models import Product, ProductImage, ProductImport

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"title"}
OPTIONAL_COLUMNS = {"description", "brand", "product_type", "image_urls"}
ALL_COLUMNS = REQUIRED_COLUMNS | OPTIONAL_COLUMNS
IMAGE_SEPARATORS = [",", "|"]


class ParseError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__(f"Parse failed: {'; '.join(errors)}")


def _normalize_header(col):
    if col is None:
        return ""
    return col.strip().lower().replace(" ", "_")


def _validate_file(file_obj, filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
        raise ParseError(
            [
                f"Unsupported file type '{ext}'. "
                f"Allowed: {', '.join(sorted(settings.ALLOWED_UPLOAD_EXTENSIONS))}"
            ]
        )
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    file_obj.seek(0, os.SEEK_END)
    size = file_obj.tell()
    file_obj.seek(0)
    if size > max_bytes:
        raise ParseError(
            [f"File size {size} bytes exceeds " f"maximum of {max_bytes} bytes"]
        )


def _read_csv(file_obj):
    text = file_obj.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    headers = [_normalize_header(h) for h in reader.fieldnames or []]
    rows = []
    for row in reader:
        normalized = {_normalize_header(k): v for k, v in row.items()}
        rows.append(normalized)
    return headers, rows


def _read_xlsx(file_obj):
    from openpyxl import load_workbook

    wb = load_workbook(file_obj, read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    raw_headers = next(rows_iter, [])
    headers = [_normalize_header(str(h)) if h else "" for h in raw_headers]
    rows = []
    for row in rows_iter:
        normalized = {}
        for i, val in enumerate(row):
            if i < len(headers):
                normalized[headers[i]] = str(val) if val is not None else ""
        rows.append(normalized)
    wb.close()
    return headers, rows


def _parse_image_urls(raw_value):
    if not raw_value or not str(raw_value).strip():
        return []
    text = str(raw_value).strip()
    for sep in IMAGE_SEPARATORS:
        if sep in text:
            return [u.strip() for u in text.split(sep) if u.strip()]
    return [text]


def _validate_headers(headers):
    errors = []
    normalized = set(headers)
    missing = REQUIRED_COLUMNS - normalized
    if missing:
        errors.append(f"Missing required column(s): {', '.join(sorted(missing))}")
    unknown = normalized - ALL_COLUMNS
    if unknown:
        logger.warning("Skipping unknown columns: %s", sorted(unknown))
    return errors


def _create_products(rows, import_obj):
    imported = 0
    failed = 0
    errors = []

    for i, row in enumerate(rows, start=2):
        title = (row.get("title") or "").strip()
        if not title:
            failed += 1
            errors.append({"row": i, "error": "Missing required field: title"})
            continue

        with transaction.atomic():
            product = Product.objects.create(
                title=title,
                description=(row.get("description") or "").strip(),
                brand=(row.get("brand") or "").strip(),
                product_type=(row.get("product_type") or "").strip(),
                raw_data=row,
            )
            image_urls = _parse_image_urls(row.get("image_urls"))
            for url in image_urls:
                ProductImage.objects.create(product=product, url=url)
            imported += 1

    return imported, failed, errors


def import_products(file_obj, filename):
    _validate_file(file_obj, filename)
    file_obj.seek(0)
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".csv":
        headers, rows = _read_csv(file_obj)
    else:
        headers, rows = _read_xlsx(file_obj)

    header_errors = _validate_headers(headers)
    if header_errors:
        raise ParseError(header_errors)

    import_obj = ProductImport.objects.create(
        file=file_obj,
        status=ProductImport.Status.PROCESSING,
        total_rows=len(rows),
    )

    try:
        imported, failed, row_errors = _create_products(rows, import_obj)
        import_obj.status = ProductImport.Status.COMPLETED
        import_obj.imported_rows = imported
        import_obj.failed_rows = failed
        import_obj.error_log = row_errors
        import_obj.completed_at = tz.now()
        import_obj.save(
            update_fields=[
                "status",
                "imported_rows",
                "failed_rows",
                "error_log",
                "completed_at",
            ]
        )
    except Exception as exc:
        logger.exception("Import failed for %s", filename)
        import_obj.status = ProductImport.Status.FAILED
        import_obj.error_log = [{"error": str(exc)}]
        import_obj.save(update_fields=["status", "error_log"])
        raise

    return import_obj
