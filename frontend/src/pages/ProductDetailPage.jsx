import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { getClassifiedProductDetail } from "../api/client";
import ConfidenceRing from "../components/ConfidenceRing";

function statusBadge(status) {
  const map = {
    approved: { bg: "#16a34a", color: "#ffffff", border: "1px solid #16a34a" },
    needs_review: {
      bg: "#eab308",
      color: "#111111",
      border: "1px solid #eab308",
    },
    failed: { bg: "#dc2626", color: "#ffffff", border: "1px solid #dc2626" },
  };
  const style = map[status] || map.needs_review;
  return (
    <span
      className="detail-badge"
      style={{
        color: style.color,
        backgroundColor: style.bg,
        border: style.border,
      }}
    >
      {String(status || "").replace(/_/g, " ")}
    </span>
  );
}

function sourceBadge(source) {
  return (
    <span
      className="detail-badge"
      style={{
        color: "#1a56db",
        backgroundColor: "#ffffff",
        border: "1px solid #1a56db",
      }}
    >
      {source || "AI"}
    </span>
  );
}

function formatValue(value) {
  if (value == null || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function prettyDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function ProductDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedImage, setSelectedImage] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    getClassifiedProductDetail(id)
      .then((data) => {
        if (!cancelled) {
          setItem(data);
          setSelectedImage(0);
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
  }, [id]);

  if (loading) {
    return (
      <p>
        <span className="spinner" /> Loading...
      </p>
    );
  }

  if (error || !item) {
    return (
      <div>
        <div className="error">{error || "Product not found."}</div>
        <button className="btn" onClick={() => navigate("/products")}>
          Back to products
        </button>
      </div>
    );
  }

  const product = item.product || {};
  const images = product.images || [];
  const rawDataEntries = Object.entries(product.raw_data || {});

  return (
    <div className="product-detail">
      <button className="btn btn-back" onClick={() => navigate("/products")}>
        ← Back to products
      </button>

      <div className="product-detail-grid">
        <div className="product-gallery">
          {images.length > 0 ? (
            <div className="gallery-main">
              <img
                className="gallery-image"
                src={images[selectedImage] || images[0]}
                alt={product.title}
              />
            </div>
          ) : (
            <div className="gallery-image gallery-image-empty">No image</div>
          )}
          {images.length > 1 && (
            <div className="gallery-thumbs">
              {images.map((url, i) => (
                <button
                  key={i}
                  type="button"
                  className={`gallery-thumb ${
                    i === selectedImage ? "gallery-thumb-active" : ""
                  }`}
                  onClick={() => setSelectedImage(i)}
                >
                  <img src={url} alt="" />
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="product-summary">
          <div className="summary-meta">
            {statusBadge(item.status)}
            {sourceBadge(item.source)}
            <span
              className="detail-badge"
              style={{
                color: "#000000",
                backgroundColor: "#ffffff",
                border: "1px solid #000000",
              }}
            >
              Confidence: {Math.round(item.confidence)}
            </span>
          </div>
          <h1 className="product-title">{product.title}</h1>
          {product.brand && <div className="product-brand">{product.brand}</div>}
          <div className="product-category">
            {item.category?.full_path || "Uncategorized"}
          </div>

          <div className="summary-facts">
            {product.product_type && (
              <div className="fact">
                <span className="fact-label">Product type</span>
                <span className="fact-value">{product.product_type}</span>
              </div>
            )}
            {product.external_id && (
              <div className="fact">
                <span className="fact-label">External ID / SKU</span>
                <span className="fact-value">{product.external_id}</span>
              </div>
            )}
            {item.reviewed_by && (
              <div className="fact">
                <span className="fact-label">Reviewed by</span>
                <span className="fact-value">{item.reviewed_by}</span>
              </div>
            )}
            {item.reviewed_at && (
              <div className="fact">
                <span className="fact-label">Reviewed at</span>
                <span className="fact-value">{prettyDate(item.reviewed_at)}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {product.description && (
        <div className="product-description">
          <h3>Description</h3>
          <p>{product.description}</p>
        </div>
      )}

      {item.correction_notes && (
        <div className="product-description">
          <h3>Correction Notes</h3>
          <p>{item.correction_notes}</p>
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
                  <td>{attr.value_display || attr.free_text_value || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {item.alternatives?.length > 0 && (
        <div className="detail-section">
          <h3>Alternative Categories</h3>
          {item.alternatives.map((alt, i) => (
            <div key={i} className="alternative-item">
              <ConfidenceRing score={alt.confidence} size={26} strokeWidth={4} />
              <span>
                {alt.category?.full_path || `Category #${alt.category_id}`}
              </span>
            </div>
          ))}
        </div>
      )}

      {product.error_message && (
        <div className="detail-section">
          <h3>Error</h3>
          <p>{product.error_message}</p>
        </div>
      )}

      {rawDataEntries.length > 0 && (
        <div className="detail-section">
          <h3>Source Data</h3>
          <table className="attr-table">
            <thead>
              <tr>
                <th>Field</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              {rawDataEntries.map(([key, value]) => (
                <tr key={key}>
                  <td>{key}</td>
                  <td className="source-data-value">{formatValue(value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="detail-footer">
        <Link className="btn" to="/products">
          Back to products
        </Link>
      </div>
    </div>
  );
}