import { useUpload } from "../context/UploadContext";

export default function UploadPage() {
  const {
    file,
    setFile,
    uploadProgress,
    importData,
    jobStatus,
    error,
    uploading,
    uploadingLabel,
    handleUpload,
    resetUpload,
  } = useUpload();

  // ---------- Import-row progress (file → DB) ----------
  // Use total_rows from the ProductImport record (raw rows in the file).
  // Falls back to jobStatus.import_total_rows streamed from the job-status
  // endpoint so the bar works even before importData refreshes.
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
  // Denominator = total rows in the file; numerator = done + needs_review + failed
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
  const allDone =
    importDone &&
    !isClassifying &&
    classifiedCount > 0;

  return (
    <div>
      <h2>Upload Products</h2>
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
                  <span className="spinner" /> {uploadingLabel}
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

        {/* Upload-to-server progress (XHR progress event) */}
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
            {importData.status === "completed" && " — "}
            {importData.status === "completed" &&
              `${importData.imported_rows} rows inserted`}
            {importData.failed_rows > 0 &&
              `, ${importData.failed_rows} failed`}
          </p>
        </div>
      )}

      {/* ---- Live streaming progress ---- */}
      {(importData || jobStatus) && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h3>Processing Status</h3>

          {/* Row counts dashboard */}
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

          {/* Bar 1 — Import progress (rows read from file → saved to DB) */}
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

          {/* Bar 2 — Classification progress */}
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
                    background: allDone ? "#22c55e" : "#ffffff",
                  }}
                />
              </div>
            </div>
          )}

          {allDone && (
            <p style={{ marginTop: "0.75rem", color: "#22c55e", fontSize: "0.95rem" }}>
              ✓ All done — view results on the Products page.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
