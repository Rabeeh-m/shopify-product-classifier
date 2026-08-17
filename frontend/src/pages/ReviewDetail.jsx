import { useState, useEffect } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import {
  getReviewDetail,
  approveClassification,
  correctClassification,
} from "../api/client";

function confidenceClass(score) {
  if (score >= 70) return "confidence-high";
  if (score >= 50) return "confidence-medium";
  return "confidence-low";
}

export default function ReviewDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionLoading, setActionLoading] = useState(false);

  // Correct form state
  const [showCorrect, setShowCorrect] = useState(false);
  const [correctCategoryId, setCorrectCategoryId] = useState("");
  const [correctAttributes, setCorrectAttributes] = useState([]);
  const [categorySearch, setCategorySearch] = useState("");
  const [categoryResults, setCategoryResults] = useState([]);

  useEffect(() => {
    setLoading(true);
    getReviewDetail(id)
      .then((data) => {
        setItem(data);
        setCorrectAttributes(
          (data.attributes || []).map((a) => ({
            name: a.attribute_name,
            value: a.free_text_value || a.value_display || "",
          }))
        );
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [id]);

  const handleApprove = async () => {
    setActionLoading(true);
    setError("");
    try {
      await approveClassification(item.id);
      navigate("/review");
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
      navigate("/review");
    } catch (err) {
      setError(err.message);
      setActionLoading(false);
    }
  };

  const handleCategorySearch = async (query) => {
    setCategorySearch(query);
    if (query.length < 2) {
      setCategoryResults([]);
      return;
    }
    try {
      const data = await fetch(
        `/api/taxonomy/categories/?search=${encodeURIComponent(query)}`
      );
      if (data.ok) {
        const json = await data.json();
        setCategoryResults(json.results || json || []);
      }
    } catch {
      /* ignore */
    }
  };

  const updateAttribute = (index, field, value) => {
    const updated = [...correctAttributes];
    updated[index] = { ...updated[index], [field]: value };
    setCorrectAttributes(updated);
  };

  const addAttribute = () => {
    setCorrectAttributes([...correctAttributes, { name: "", value: "" }]);
  };

  const removeAttribute = (index) => {
    setCorrectAttributes(correctAttributes.filter((_, i) => i !== index));
  };

  if (loading) {
    return (
      <p>
        <span className="spinner" /> Loading...
      </p>
    );
  }

  if (error && !item) {
    return <div className="error">{error}</div>;
  }

  if (!item) return null;

  return (
    <div>
      <Link to="/review" style={{ fontSize: "0.9rem" }}>
        &larr; Back to queue
      </Link>

      {error && <div className="error" style={{ marginTop: "0.5rem" }}>{error}</div>}

      <div className="card" style={{ marginTop: "1rem" }}>
        <div style={{ display: "flex", gap: "1rem" }}>
          {item.product.image_urls?.[0] && (
            <img
              src={item.product.image_urls[0]}
              alt=""
              style={{
                width: "120px",
                height: "120px",
                objectFit: "cover",
                borderRadius: "6px",
              }}
            />
          )}
          <div style={{ flex: 1 }}>
            <h2 style={{ marginBottom: "0.25rem" }}>{item.product.title}</h2>
            <span className={`confidence-badge ${confidenceClass(item.confidence)}`}>
              {Math.round(item.confidence)}% confidence
            </span>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="detail-section">
          <h3>AI Classification</h3>
          <p>
            <strong>Category:</strong> {item.category?.full_path || "None"}
          </p>
        </div>

        {item.alternatives?.length > 0 && (
          <div className="detail-section">
            <h3>Alternatives</h3>
            {item.alternatives.map((alt, i) => (
              <div key={i} className="alternative-item">
                <span className={`confidence-badge ${confidenceClass(alt.confidence)}`}>
                  {Math.round(alt.confidence)}%
                </span>
                <span>{alt.category?.full_path || `Category #${alt.category_id}`}</span>
              </div>
            ))}
          </div>
        )}

        {item.attributes?.length > 0 && (
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
                {item.attributes.map((attr, i) => (
                  <tr key={i}>
                    <td>{attr.attribute_name}</td>
                    <td>{attr.value_display || attr.free_text_value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

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
            onClick={() => setShowCorrect(!showCorrect)}
            disabled={actionLoading}
          >
            {showCorrect ? "Cancel" : "Correct"}
          </button>
        </div>
      </div>

      {showCorrect && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h3 style={{ marginBottom: "0.75rem" }}>Correct Classification</h3>
          <form className="correct-form" onSubmit={handleCorrect}>
            <div className="field">
              <label>New Category</label>
              <input
                type="text"
                placeholder="Search category..."
                value={categorySearch}
                onChange={(e) => handleCategorySearch(e.target.value)}
              />
              {categoryResults.length > 0 && (
                <select
                  value={correctCategoryId}
                  onChange={(e) => {
                    setCorrectCategoryId(e.target.value);
                    const selected = categoryResults.find(
                      (c) => String(c.id) === e.target.value
                    );
                    if (selected) setCategorySearch(selected.full_path);
                    setCategoryResults([]);
                  }}
                  style={{ marginTop: "0.25rem", width: "100%" }}
                >
                  <option value="">Select a category</option>
                  {categoryResults.map((cat) => (
                    <option key={cat.id} value={cat.id}>
                      {cat.full_path}
                    </option>
                  ))}
                </select>
              )}
              {!categoryResults.length && correctCategoryId && (
                <small style={{ color: "#666" }}>
                  Selected category ID: {correctCategoryId}
                </small>
              )}
            </div>

            <div className="field">
              <label>Attributes</label>
              {correctAttributes.map((attr, i) => (
                <div key={i} style={{ display: "flex", gap: "0.5rem", marginBottom: "0.25rem" }}>
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
                    onClick={() => removeAttribute(i)}
                    style={{ padding: "0.25rem 0.5rem" }}
                  >
                    &times;
                  </button>
                </div>
              ))}
              <button
                type="button"
                className="btn"
                onClick={addAttribute}
                style={{ marginTop: "0.25rem", border: "1px dashed #ccc" }}
              >
                + Add attribute
              </button>
            </div>

            <button className="btn btn-success" type="submit" disabled={actionLoading}>
              Submit correction
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
