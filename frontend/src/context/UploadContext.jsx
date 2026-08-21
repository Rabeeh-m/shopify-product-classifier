import { createContext, useContext, useState, useRef, useEffect } from "react";
import { uploadFile, getImportStatus, getJobStatus } from "../api/client";

const STORAGE_KEY = "active_import_id";

function getStoredImportId() {
  try {
    const id = localStorage.getItem(STORAGE_KEY);
    return id ? Number(id) : null;
  } catch {
    return null;
  }
}

function storeImportId(id) {
  try {
    localStorage.setItem(STORAGE_KEY, String(id));
  } catch {
    /* ignore */
  }
}

function clearStoredImportId() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

const UploadContext = createContext(null);

export function UploadProvider({ children }) {
  const [file, setFile] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [importData, setImportData] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadingLabel, setUploadingLabel] = useState("");
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
        if (imp.status === "completed" || imp.status === "failed") {
          stopPolling();
          clearStoredImportId();
        }
      } catch {
        /* ignore poll errors */
      }
    }, 2000);
  };

  // On mount, restore any in-progress import from localStorage
  useEffect(() => {
    const storedId = getStoredImportId();
    if (storedId) {
      getImportStatus(storedId)
        .then((imp) => {
          setImportData(imp);
          if (imp.status === "completed" || imp.status === "failed") {
            clearStoredImportId();
          } else {
            startPolling(storedId);
          }
        })
        .catch(() => {
          clearStoredImportId();
        });
    }

    // Clean up polling when the entire app unmounts (e.g. page refresh)
    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      storeImportId(data.id);
      setUploadingLabel("Processing...");
      startPolling(data.id);
    } catch (err) {
      setError(err.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const resetUpload = () => {
    stopPolling();
    clearStoredImportId();
    setFile(null);
    setUploadProgress(0);
    setImportData(null);
    setJobStatus(null);
    setError("");
    setUploading(false);
    setUploadingLabel("");
  };

  return (
    <UploadContext.Provider
      value={{
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
      }}
    >
      {children}
    </UploadContext.Provider>
  );
}

export function useUpload() {
  const ctx = useContext(UploadContext);
  if (!ctx) throw new Error("useUpload must be used within UploadProvider");
  return ctx;
}
