import { useState, useEffect } from "react";
import {
  getReviewList,
  approveClassification,
  correctClassification,
  searchCategories,
} from "../api/client";

function confidenceClass(score) {
  if (score >= 70) return "confidence-high";
  if (score >= 50) return "confidence-medium";
  return "confidence-low";
}

function ReviewItemDetail({ item, onResolved }) {
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState("");
  const [showCorrect, setShowCorrect] = useState(false);
  const [correctCategoryId, setCorrectCategoryId] = useState("");
  const [correctAttributes, setCorrectAttributes] = useState(
    (item.attributes || []).map((a) => ({
      name: a.attribute_name,
      value: a.value_display || a.free_text_value || "",
    }))
  );
  const [categoryResults, setCategoryResults] = useState([]);

  const handleCategorySearch = async (query) => {
    if (query.length < 2) {
      setCategoryResults([]);
      return;
    }
    try {
      const results = await searchCategories(query);
      setCategoryResults(results || []);
    } catch {
      /* ignore */
    }
  };

  const handleApprove = async () => {
    setActionLoading(true);
    setError("");
    try {
      await approveClassification(item.id);
      onResolved(item.id);
    } catch (err) {
      setError(err.message);
      setActionLoading(false);
    }
  };

  const handleCorrect = async (e) => {
    e.preventDefault();
    setActionLoading(true);
    setError("");
    try {
      await correctClassification(item.id, {
        categoryId: correctCategoryId ? Number(correctCategoryId) : undefined,
        attributes: correctAttributes.length > 0 ? correctAttributes : undefined,
      });
      onResolved(item.id);
    } catch (err) {
      setError(err.message);
      setActionLoading(false);
    }
  };

  const updateAttribute = (index, field, value) => {
    const updated = [...correctAttributes];
    updated[index] = { ...updated[index], [field]: value };
    setCorrectAttributes(updated);
  };

  return (
    <div className="review-expand">
      {error && <div className="error">{error}</div>}

      <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start" }}>
        {item.product.image_urls?.[0] && (
          <img
            src={item.product.image_urls[0]}
            alt=""
            style={{
              width: "96px",
              height: "96px",
              objectFit: "cover",
              borderRadius: "6px",
              border: "1px solid var(--border-color)",
            }}
          />
        )}
        <div style={{ flex: 1 }}>
          <h3 style={{ marginBottom: "0.5rem" }}>AI Classification</h3>
          <p>{item.category?.full_path || "None"}</p>
        </div>
      </div>

      {item.alternatives?.length > 0 && (
        <div className="detail-section" style={{ marginTop: "1rem", paddingTop: "1rem" }}>
          <h3>Alternatives</h3>
          {item.alternatives.map((alt, i) => (
            <div key={i} className="alternative-item">
              <span className={`confidence-badge ${confidenceClass(alt.confidence)}`}>
                {Math.round(alt.confidence)}%
              </span>
              <span>
                {alt.category?.full_path || `Category #${alt.category_id}`}
              </span>
            </div>
          ))}
        </div>
      )}

      {correctAttributes.length > 0 && (
        <div className="detail-section">
          <h3>Attributes</h3>
          <table className="attr-table">
            <thead>
              <tr>
                <th>Attribute</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              {correctAttributes.map((attr, i) => (
                <tr key={i}>
                  <td>{attr.name}</td>
                  <td>{attr.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!showCorrect ? (
        <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}>
          <button
            className="btn btn-success"
            onClick={handleApprove}
            disabled={actionLoading}
          >
            Approve as-is
          </button>
          <button
            className="btn btn-primary"
            onClick={() => setShowCorrect(true)}
            disabled={actionLoading}
          >
            Correct
          </button>
        </div>
      ) : (
        <form
          className="correct-form"
          onSubmit={handleCorrect}
          style={{ marginTop: "1rem" }}
        >
          <div className="field">
            <label>New Category</label>
            <input
              type="text"
              placeholder="Search category..."
              onChange={(e) => handleCategorySearch(e.target.value)}
            />
            {categoryResults.length > 0 && (
              <select
                value={correctCategoryId}
                onChange={(e) => setCorrectCategoryId(e.target.value)}
                style={{ marginTop: "0.25rem" }}
              >
                <option value="">Select a category</option>
                {categoryResults.map((cat) => (
                  <option key={cat.id} value={cat.id}>
                    {cat.full_path}
                  </option>
                ))}
              </select>
            )}
          </div>

          <div className="field">
            <label>Attributes</label>
            {correctAttributes.map((attr, i) => (
              <div
                key={i}
                style={{ display: "flex", gap: "0.5rem", marginBottom: "0.25rem" }}
              >
                <input
                  type="text"
                  placeholder="Name"
                  value={attr.name}
                  onChange={(e) => updateAttribute(i, "name", e.target.value)}
                  style={{ flex: 1 }}
                />
                <input
                  type="text"
                  placeholder="Value"
                  value={attr.value}
                  onChange={(e) => updateAttribute(i, "value", e.target.value)}
                  style={{ flex: 1 }}
                />
                <button
                  type="button"
                  className="btn btn-danger"
                  onClick={() =>
                    setCorrectAttributes(
                      correctAttributes.filter((_, j) => j !== i)
                    )
                  }
                  style={{ padding: "0.25rem 0.5rem" }}
                >
                  &times;
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn"
              onClick={() =>
                setCorrectAttributes([...correctAttributes, { name: "", value: "" }])
              }
              style={{ marginTop: "0.25rem", border: "1px dashed #ccc" }}
            >
              + Add attribute
            </button>
          </div>

          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button
              className="btn btn-success"
              type="submit"
              disabled={actionLoading}
            >
              Submit correction
            </button>
            <button
              className="btn"
              type="button"
              onClick={() => setShowCorrect(false)}
              disabled={actionLoading}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

const PAGE_SIZE = 25;

export default function ReviewPage() {
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const totalPages = Math.max(1, Math.ceil(count / PAGE_SIZE));

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

  const handleResolved = (id) => {
    setItems((prev) => prev.filter((i) => i.id !== id));
    setCount((c) => Math.max(0, c - 1));
    setExpandedId(null);
  };

  const handleSearch = (e) => {
    e.preventDefault();
    setPage(1);
  };

  return (
    <div>
      <div
        style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "1rem" }}
      >
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
              <div key={item.id}>
                <div
                  className="review-item"
                  onClick={() =>
                    setExpandedId(expandedId === item.id ? null : item.id)
                  }
                >
                  {item.product.image_urls?.[0] ? (
                    <img className="thumb" src={item.product.image_urls[0]} alt="" />
                  ) : (
                    <div className="thumb" />
                  )}
                  <div className="info">
                    <div className="title">{item.product.title}</div>
                    <div className="category">
                      {item.category?.full_path || "Uncategorized"}
                    </div>
                  </div>
                  <span
                    className={`confidence-badge ${confidenceClass(item.confidence)}`}
                  >
                    {Math.round(item.confidence)}%
                  </span>
                </div>
                {expandedId === item.id && (
                  <ReviewItemDetail item={item} onResolved={handleResolved} />
                )}
              </div>
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
