import { useState, useEffect, useRef } from "react";
import { getClassifiedProducts, getJobStatus, clearAllProducts } from "../api/client";

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

const POLL_INTERVAL_MS = 3000; // re-fetch while jobs are running

export default function ClassifiedProducts() {
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(0);
  const [availableCategories, setAvailableCategories] = useState([]);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [clearing, setClearing] = useState(false);

  // Live-refresh while products are being classified
  const [isProcessing, setIsProcessing] = useState(false);

  const totalPages = Math.max(1, Math.ceil(count / PAGE_SIZE));

  const fetchRef = useRef(null);

  const fetchProducts = () => {
    setError("");
    getClassifiedProducts({
      page,
      search,
      status: statusFilter,
      categoryId,
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

  useEffect(() => {
    setLoading(true);
    fetchRef.current();
  }, [page, search, statusFilter, categoryId]);

  // Poll while any classification work is in flight
  useEffect(() => {
    let stopped = false;
    let timer = null;
    const tick = async () => {
      try {
        const jobs = await getJobStatus();
        if (stopped) return;
        const busy = jobs.pending > 0 || jobs.processing > 0;
        setIsProcessing(busy);
        if (busy) {
          fetchRef.current();
          timer = setTimeout(tick, POLL_INTERVAL_MS);
        }
      } catch {
        /* ignore */
      }
    };
    tick();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const handleSearch = (e) => {
    e.preventDefault();
    setPage(1);
  };

  const handleCategoryChange = (e) => {
    setCategoryId(e.target.value);
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
            <span
              className="spinner"
              style={{ width: "0.9rem", height: "0.9rem", borderWidth: "1.5px" }}
            />{" "}
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
          onChange={(e) => {
            setStatusFilter(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All Statuses</option>
          <option value="approved">Approved</option>
          <option value="needs_review">Needs Review</option>
          <option value="failed">Failed</option>
        </select>
        <select
          id="category-filter"
          value={categoryId}
          onChange={handleCategoryChange}
        >
          <option value="">All Categories</option>
          {availableCategories.map((root) =>
            root.children.length > 0 ? (
              <optgroup key={root.id} label={`${root.name} (${root.count})`}>
                {root.children.map((sub) => (
                  <option key={sub.id} value={sub.id}>
                    {sub.name} ({sub.count})
                  </option>
                ))}
              </optgroup>
            ) : (
              <option key={root.id} value={root.id}>
                {root.name} ({root.count})
              </option>
            )
          )}
        </select>
      </div>

      {error && <div className="error">{error}</div>}

      {loading ? (
        <p>
          <span className="spinner" /> Loading...
        </p>
      ) : items.length === 0 ? (
        <div className="card">
          <p>No classified products found.</p>
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
