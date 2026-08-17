import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { getReviewList } from "../api/client";

function confidenceClass(score) {
  if (score >= 70) return "confidence-high";
  if (score >= 50) return "confidence-medium";
  return "confidence-low";
}

export default function ReviewPage() {
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const totalPages = Math.max(1, Math.ceil(count / 25));

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    getReviewList({ page, search })
      .then((data) => {
        if (!cancelled) {
          setItems(data.results || []);
          setCount(data.count || 0);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [page, search]);

  const handleSearch = (e) => {
    e.preventDefault();
    setPage(1);
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "1rem" }}>
        <h2>Review Queue</h2>
        <span style={{ color: "#666" }}>{count} items</span>
      </div>

      <form onSubmit={handleSearch} style={{ marginBottom: "1rem" }}>
        <input
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

      {error && <div className="error">{error}</div>}

      {loading ? (
        <p>
          <span className="spinner" /> Loading...
        </p>
      ) : items.length === 0 ? (
        <div className="card">
          <p>No items need review.</p>
        </div>
      ) : (
        <>
          <div className="review-list">
            {items.map((item) => (
              <Link
                key={item.id}
                to={`/review/${item.id}`}
                style={{ textDecoration: "none", color: "inherit" }}
              >
                <div className="review-item">
                  {item.product.image_urls?.[0] ? (
                    <img
                      className="thumb"
                      src={item.product.image_urls[0]}
                      alt=""
                    />
                  ) : (
                    <div className="thumb" />
                  )}
                  <div className="info">
                    <div className="title">{item.product.title}</div>
                    <div className="category">
                      {item.category?.full_path || "Uncategorized"}
                    </div>
                  </div>
                  <span className={`confidence-badge ${confidenceClass(item.confidence)}`}>
                    {Math.round(item.confidence)}%
                  </span>
                </div>
              </Link>
            ))}
          </div>

          <div className="pagination">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)}>
              Previous
            </button>
            <span>
              Page {page} of {totalPages}
            </span>
            <button disabled={page >= totalPages} onClick={() => setPage(page + 1)}>
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}
