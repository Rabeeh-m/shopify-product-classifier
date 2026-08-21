import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import {
  uploadFile,
  getImportStatus,
  getLatestImport,
  getJobStatus,
} from "../api/client";

const POLL_INTERVAL_MS = 2000;

export default function UploadPage() {
  const [file, setFile] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [importData, setImportData] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const pollRef = useRef(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startPolling = (importId) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const [imp, jobs] = await Promise.all([
          getImportStatus(importId),
          getJobStatus(),
        ]);
        setImportData(imp);
        setJobStatus(jobs);
        if (
          imp.status === "completed" &&
          jobs &&
          jobs.pending === 0 &&
          jobs.processing === 0
        ) {
          stopPolling();
        }
      } catch {
        /* ignore poll errors */
      }
    }, POLL_INTERVAL_MS);
  };

  useEffect(() => stopPolling, []);

  // Restore the last import's progress when returning to this page.
  useEffect(() => {
    let cancelled = false;
    getLatestImport()
      .then(async (imp) => {
        if (cancelled || !imp) return;
        setImportData(imp);
        try {
          const jobs = await getJobStatus();
          if (cancelled) return;
          setJobStatus(jobs);
          const busy =
            imp.status === "processing" ||
            (jobs && (jobs.pending > 0 || jobs.processing > 0));
          if (busy) startPolling(imp.id);
        } catch {
          /* ignore */
        }
      })
      .catch(() => {
        /* no imports yet */
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!file) return;
    setError("");
    setUploading(true);
    setUploadProgress(0);
    try {
      const data = await uploadFile(file, setUploadProgress);
      setImportData(data);
      startPolling(data.id);
    } catch (err) {
      setError(err.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const resetUpload = () => {
    stopPolling();
    setFile(null);
    setUploadProgress(0);
    setImportData(null);
    setJobStatus(null);
    setError("");
    setUploading(false);
  };

  // ---------- Import-row progress (file → DB) ----------
  const importTotalRows =
    (importData?.total_rows > 0 ? importData.total_rows : null) ||
    jobStatus?.import_total_rows ||
    0;
  const importedRows =
    (importData?.imported_rows ?? null) !== null
      ? importData.imported_rows
      : jobStatus?.import_imported_rows ?? 0;
  const importPercent =
    importTotalRows > 0
      ? Math.min(100, Math.round((importedRows / importTotalRows) * 100))
      : 0;
  const importDone =
    importData?.status === "completed" || importData?.status === "failed";

  // ---------- Classification progress ----------
  const classifiedCount = jobStatus
    ? jobStatus.done + jobStatus.needs_review + jobStatus.failed
    : 0;
  const classifyDenominator = importTotalRows || importedRows || 0;
  const classifyPercent =
    classifyDenominator > 0
      ? Math.min(100, Math.round((classifiedCount / classifyDenominator) * 100))
      : 0;

  const isImporting =
    importData?.status === "processing" &&
    (importedRows < importTotalRows || importTotalRows === 0);
  const isClassifying =
    jobStatus && (jobStatus.pending > 0 || jobStatus.processing > 0);
  const allDone = importDone && !isClassifying && classifiedCount > 0;

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "1rem",
        }}
      >
        <h2>Upload Products</h2>
        <Link
          id="view-products-btn"
          className="btn btn-success"
          to="/products"
        >
          View Products
        </Link>
      </div>
      <div className="card" style={{ marginTop: "1rem" }}>
        <form onSubmit={handleUpload}>
          <div className="field">
            <input
              id="file-input"
              type="file"
              accept=".csv,.xlsx"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </div>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <button
              id="upload-btn"
              className="btn btn-primary"
              type="submit"
              disabled={!file || uploading}
            >
              {uploading ? (
                <>
                  <span className="spinner" /> Uploading...
                </>
              ) : (
                "Upload & Process"
              )}
            </button>
            {(importData || error) && !uploading && (
              <button
                id="clear-btn"
                className="btn"
                type="button"
                onClick={resetUpload}
              >
                Clear
              </button>
            )}
          </div>
        </form>

        {uploading && (
          <div style={{ marginTop: "1rem" }}>
            <div className="progress-bar">
              <div
                className="progress-bar-fill"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
            <small>{uploadProgress}% uploaded to server</small>
          </div>
        )}

        {error && <div className="error" style={{ marginTop: "1rem" }}>{error}</div>}
      </div>

      {/* ---- Import record summary ---- */}
      {importData && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h3>Import #{importData.id}</h3>
          <p>
            Status: <strong>{importData.status}</strong>
            {importData.status === "completed" &&
              ` — ${importData.imported_rows} rows inserted`}
            {importData.failed_rows > 0 &&
              `, ${importData.failed_rows} failed`}
          </p>
        </div>
      )}

      {/* ---- Live progress ---- */}
      {(importData || jobStatus) && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h3>Processing Status</h3>

          {jobStatus && (
            <div className="status-grid">
              <div className="status-item">
                <div className="count">{jobStatus.pending}</div>
                <div className="label">Pending</div>
              </div>
              <div className="status-item">
                <div className="count">{jobStatus.processing}</div>
                <div className="label">Processing</div>
              </div>
              <div className="status-item">
                <div className="count">{jobStatus.done}</div>
                <div className="label">Approved</div>
              </div>
              <div className="status-item">
                <div className="count">{jobStatus.needs_review}</div>
                <div className="label">Needs Review</div>
              </div>
              <div className="status-item">
                <div className="count">{jobStatus.failed}</div>
                <div className="label">Failed</div>
              </div>
            </div>
          )}

          {importTotalRows > 0 && (
            <div style={{ marginTop: "1rem" }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: "0.8rem",
                  color: "var(--text-secondary)",
                  marginBottom: "0.25rem",
                }}
              >
                <span>
                  {isImporting ? (
                    <><span className="spinner" style={{ width: "0.9rem", height: "0.9rem", borderWidth: "1.5px" }} />{" "}Importing rows…</>
                  ) : importDone ? (
                    "✓ Import complete"
                  ) : (
                    "Import"
                  )}
                </span>
                <span>
                  {importedRows.toLocaleString()} / {importTotalRows.toLocaleString()} rows
                </span>
              </div>
              <div className="progress-bar">
                <div
                  className="progress-bar-fill"
                  style={{ width: `${importPercent}%` }}
                />
              </div>
            </div>
          )}

          {classifyDenominator > 0 && (
            <div style={{ marginTop: "0.75rem" }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: "0.8rem",
                  color: "var(--text-secondary)",
                  marginBottom: "0.25rem",
                }}
              >
                <span>
                  {isClassifying ? (
                    <><span className="spinner" style={{ width: "0.9rem", height: "0.9rem", borderWidth: "1.5px" }} />{" "}Classifying products…</>
                  ) : allDone ? (
                    "✓ Classification complete"
                  ) : (
                    "Classification"
                  )}
                </span>
                <span>
                  {classifiedCount.toLocaleString()} / {classifyDenominator.toLocaleString()} products classified
                </span>
              </div>
              <div className="progress-bar">
                <div
                  className="progress-bar-fill"
                  style={{
                    width: `${classifyPercent}%`,
                    background: allDone ? "#22c55e" : undefined,
                  }}
                />
              </div>
            </div>
          )}

          {allDone && (
            <p style={{ marginTop: "0.75rem", color: "#22c55e", fontSize: "0.95rem" }}>
              ✓ All done —{" "}
              <Link to="/products" style={{ color: "#22c55e", fontWeight: 600 }}>
                view results on the Products page
              </Link>
              .
            </p>
          )}
        </div>
      )}
    </div>
  );
}
