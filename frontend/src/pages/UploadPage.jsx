import { useState, useEffect, useRef } from "react";
import { uploadFile, getImportStatus, getJobStatus } from "../api/client";

export default function UploadPage() {
  const [file, setFile] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [importData, setImportData] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadingLabel, setUploadingLabel] = useState("");
  const pollRef = useRef(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const startPolling = (importId) => {
    pollRef.current = setInterval(async () => {
      try {
        const [imp, jobs] = await Promise.all([
          getImportStatus(importId),
          getJobStatus(),
        ]);
        setImportData(imp);
        setJobStatus(jobs);
        if (
          imp.status === "completed" ||
          imp.status === "failed"
        ) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
        const totalActive = jobs.pending + jobs.processing;
        if (totalActive === 0 && imp.status === "completed" && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch {
        /* ignore poll errors */
      }
    }, 2000);
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!file) return;
    setError("");
    setUploading(true);
    setUploadingLabel("Uploading...");
    setUploadProgress(0);
    try {
      const data = await uploadFile(file, setUploadProgress);
      setImportData(data);
      setUploadingLabel("Processing...");
      startPolling(data.id);
    } catch (err) {
      setError(err.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const totalProcessed = jobStatus
    ? jobStatus.done + jobStatus.needs_review + jobStatus.failed
    : 0;
  const totalExpected = importData ? importData.imported_rows : 0;
  const isProcessing =
    jobStatus && (jobStatus.pending > 0 || jobStatus.processing > 0);

  return (
    <div>
      <h2>Upload Products</h2>
      <div className="card" style={{ marginTop: "1rem" }}>
        <form onSubmit={handleUpload}>
          <div className="field">
            <input
              type="file"
              accept=".csv,.xlsx"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </div>
          <button
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
        </form>

        {uploading && (
          <div style={{ marginTop: "1rem" }}>
            <div className="progress-bar">
              <div
                className="progress-bar-fill"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
            <small>{uploadProgress}% uploaded</small>
          </div>
        )}

        {error && <div className="error" style={{ marginTop: "1rem" }}>{error}</div>}
      </div>

      {importData && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h3>Import #{importData.id}</h3>
          <p>
            Status: <strong>{importData.status}</strong>
            {importData.status === "completed" && " — "}
            {importData.imported_rows} imported
            {importData.failed_rows > 0 && `, ${importData.failed_rows} failed`}
          </p>
        </div>
      )}

      {jobStatus && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h3>Processing Status</h3>
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
              <div className="label">Done</div>
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
          {totalExpected > 0 && (
            <div style={{ marginTop: "0.5rem" }}>
              <div className="progress-bar">
                <div
                  className="progress-bar-fill"
                  style={{
                    width: `${Math.round((totalProcessed / totalExpected) * 100)}%`,
                  }}
                />
              </div>
              <small>
                {totalProcessed} / {totalExpected} products classified
              </small>
            </div>
          )}
          {isProcessing && (
            <p style={{ marginTop: "0.5rem" }}>
              <span className="spinner" /> Processing...
            </p>
          )}
          {!isProcessing && importData?.status === "completed" && (
            <p style={{ marginTop: "0.5rem", color: "#16a34a" }}>
              Processing complete.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
