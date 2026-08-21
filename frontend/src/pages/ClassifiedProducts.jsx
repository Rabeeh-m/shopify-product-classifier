import { useState, useEffect, useRef } from "react";
import { getClassifiedProducts, clearAllProducts } from "../api/client";
import { useUpload } from "../context/UploadContext";

const PAGE_SIZE = 20;

function confidenceClass(score) {
  if (score >= 70) return "confidence-high";
  if (score >= 50) return "confidence-medium";
  return "confidence-low";
}

function statusBadge(status) {
  const map = {
    approved: { bg: "#000000", color: "#ffffff", border: "1px solid #000000" },
    needs_review: { bg: "#ffffff", color: "#111111", border: "1px solid #111111" },
    failed: { bg: "#f0f0f0", color: "#888888", border: "1px solid #dddddd" },
  };
  const style = map[status] || map.needs_review;
  return (
    <span
      style={{
        display: "inline-block",
        padding: "0.2rem 0.5rem",
        borderRadius: "4px",
        fontSize: "0.8rem",
        fontWeight: "600",
        whiteSpace: "nowrap",
        color: style.color,
        backgroundColor: style.bg,
        border: style.border,
      }}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

function ProductCard({ item }) {
  const imageUrl = item.product.image_urls?.[0];
  return (
    <div className="product-card">
      {imageUrl ? (
        <img
          className="card-image"
          src={imageUrl}
          alt={item.product.title}
          loading="lazy"
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
        />
      ) : (
        <div className="card-image-placeholder">No image</div>
      )}
      <div className="card-body">
        <div className="card-title" title={item.product.title}>
          {item.product.title}
        </div>
        <div className="card-category">
          {item.category?.full_path || "Uncategorized"}
        </div>
        {item.product.brand && <div className="card-brand">{item.product.brand}</div>}
        {item.correction_notes && (
          <div className="correction-note" title={item.correction_notes}>
            Note: {item.correction_notes}
          </div>
        )}
        <div className="card-badges">
          <span className={`confidence-badge ${confidenceClass(item.confidence)}`}>
            {Math.round(item.confidence)}%
          </span>
          {statusBadge(item.status)}
        </div>
      </div>
    </div>
  );
}

/**
 * Single hierarchical category section. Options come from the products in
 * the current listing (passed up by the API), not the static taxonomy.
 * Click a name to filter; click the ">" icon to expand its subcategories.
 */
function HierarchicalCategorySelect({ tree, categoryId, subcategoryId, onSelect }) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState({});
  const containerRef = useRef(null);

  const selectedSub = tree
    .flatMap((r) => r.children)
    .find((c) => String(c.id) === String(subcategoryId));
  const selectedRoot =
    tree.find((r) => String(r.id) === String(categoryId)) ||
    (selectedSub && tree.find((r) => r.children.includes(selectedSub)));

  // Auto-expand the branch holding the current selection when opening
  useEffect(() => {
    if (open && selectedRoot) {
      setExpanded((prev) => ({ ...prev, [selectedRoot.id]: true }));
    }
  }, [open, selectedRoot]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const onDocClick = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const triggerLabel = selectedSub
    ? `${selectedRoot.name} > ${selectedSub.name}`
    : selectedRoot
      ? selectedRoot.name
      : "All Categories";

  const select = (rootId, subId) => {
    onSelect(rootId, subId);
    setOpen(false);
  };

  const toggleExpand = (id) =>
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));

  return (
    <div className="hier-select" ref={containerRef}>
      <button
        id="category-filter"
        type="button"
        className={`hier-trigger ${open ? "open" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="hier-trigger-label">{triggerLabel}</span>
        <span className="caret">▼</span>
      </button>

      {open && (
        <div className="hier-panel">
          <div className={`hier-item-row ${!categoryId && !subcategoryId ? "active" : ""}`}>
            <button
              type="button"
              className="hier-label"
              onClick={() => select("", "")}
            >
              All Categories
            </button>
          </div>

          {tree.length === 0 && (
            <div className="hier-empty">No categorized products listed.</div>
          )}

          {tree.map((root) => {
            const rootActive =
              String(root.id) === String(categoryId) && !subcategoryId;
            const isOpen = !!expanded[root.id];
            return (
              <div key={root.id}>
                <div className={`hier-item-row ${rootActive ? "active" : ""}`}>
                  <button
                    type="button"
                    className={`hier-label ${rootActive ? "active" : ""}`}
                    onClick={() => select(String(root.id), "")}
                  >
                    <span>{root.name}</span>
                    <span className="hier-count">{root.count}</span>
                  </button>
                  {root.children.length > 0 && (
                    <button
                      type="button"
                      className={`hier-toggle ${isOpen ? "open" : ""}`}
                      aria-label={`${isOpen ? "Collapse" : "Expand"} ${root.name} subcategories`}
                      onClick={() => toggleExpand(root.id)}
                    >
                      &gt;
                    </button>
                  )}
                </div>

                {isOpen &&
                  root.children.map((sub) => {
                    const subActive = String(sub.id) === String(subcategoryId);
                    return (
                      <div
                        key={sub.id}
                        className={`hier-item-row hier-sublist-row ${subActive ? "active" : ""}`}
                      >
                        <button
                          type="button"
                          className={`hier-label ${subActive ? "active" : ""}`}
                          onClick={() => select(String(root.id), String(sub.id))}
                        >
                          <span>{sub.name}</span>
                          <span className="hier-count">{sub.count}</span>
                        </button>
                      </div>
                    );
                  })}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

const POLL_INTERVAL_MS = 3000; // re-fetch while jobs are running

export default function ClassifiedProducts() {
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(0);
  const [availableCategories, setAvailableCategories] = useState([]);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [subcategoryId, setSubcategoryId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [clearing, setClearing] = useState(false);

  // Subscribe to global job status so we know when to auto-refresh
  const { jobStatus } = useUpload();
  const isProcessing =
    jobStatus && (jobStatus.pending > 0 || jobStatus.processing > 0);

  // A selected subcategory takes precedence over its parent category
  const activeCategoryId = subcategoryId || categoryId;

  const totalPages = Math.max(1, Math.ceil(count / PAGE_SIZE));

  // Keep a ref so the polling interval can always read latest filters/page
  const fetchRef = useRef(null);

  const fetchProducts = () => {
    setError("");
    getClassifiedProducts({
      page,
      search,
      status: statusFilter,
      categoryId: activeCategoryId,
    })
      .then((data) => {
        setItems(data.results || []);
        setCount(data.count || 0);
        setAvailableCategories(data.available_categories || []);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  };

  fetchRef.current = fetchProducts;

  // Initial load + re-load when filters/page change
  useEffect(() => {
    setLoading(true);
    fetchRef.current();
  }, [page, search, statusFilter, activeCategoryId]);

  // Live polling while there are pending/processing jobs
  useEffect(() => {
    if (!isProcessing) return;

    const id = setInterval(() => {
      fetchRef.current();
    }, POLL_INTERVAL_MS);

    return () => clearInterval(id);
  }, [isProcessing]);

  const handleSearch = (e) => {
    e.preventDefault();
    setPage(1);
  };

  const handleStatusChange = (e) => {
    setStatusFilter(e.target.value);
    setPage(1);
  };

  const handleCategorySelect = (rootId, subId) => {
    setCategoryId(rootId);
    setSubcategoryId(subId);
    setPage(1);
  };

  const handleClearAll = async () => {
    if (
      !window.confirm(
        "This will delete all products, classifications, and imports. Are you sure?"
      )
    ) {
      return;
    }
    setClearing(true);
    setError("");
    try {
      await clearAllProducts();
      setItems([]);
      setCount(0);
      setPage(1);
    } catch (err) {
      setError(err.message);
    } finally {
      setClearing(false);
    }
  };

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "1rem",
          marginBottom: "1rem",
          flexWrap: "wrap",
        }}
      >
        <h2>Classified Products</h2>
        <span style={{ color: "#666" }}>{count.toLocaleString()} products</span>
        {isProcessing && (
          <span style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>
            <span className="spinner" style={{ width: "0.9rem", height: "0.9rem", borderWidth: "1.5px" }} />{" "}
            Live updating…
          </span>
        )}
        <div style={{ marginLeft: "auto" }}>
          <button
            id="clear-all-btn"
            className="btn btn-danger"
            onClick={handleClearAll}
            disabled={clearing || count === 0}
          >
            {clearing ? "Clearing..." : "Clear All Products"}
          </button>
        </div>
      </div>

      <div className="filter-bar">
        <form onSubmit={handleSearch}>
          <input
            id="search-input"
            type="search"
            placeholder="Search by product title..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            style={{ width: "300px" }}
          />
        </form>
        <select
          id="status-filter"
          value={statusFilter}
          onChange={handleStatusChange}
        >
          <option value="">All Statuses</option>
          <option value="approved">Approved</option>
          <option value="needs_review">Needs Review</option>
          <option value="failed">Failed</option>
        </select>
        <HierarchicalCategorySelect
          tree={availableCategories}
          categoryId={categoryId}
          subcategoryId={subcategoryId}
          onSelect={handleCategorySelect}
        />
      </div>

      {error && <div className="error">{error}</div>}

      {loading ? (
        <p>
          <span className="spinner" /> Loading...
        </p>
      ) : items.length === 0 ? (
        <div className="card">
          <p>
            {isProcessing
              ? "Products are being classified — they will appear here shortly…"
              : "No classified products found."}
          </p>
        </div>
      ) : (
        <>
          <div className="product-grid">
            {items.map((item) => (
              <ProductCard key={item.id} item={item} />
            ))}
          </div>

          <div className="pagination">
            <button
              id="prev-page-btn"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              Previous
            </button>
            <span>
              Page {page} of {totalPages}
            </span>
            <button
              id="next-page-btn"
              disabled={page >= totalPages}
              onClick={() => setPage(page + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}
