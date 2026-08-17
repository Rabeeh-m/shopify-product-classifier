const BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const token = localStorage.getItem("token");

  const headers = { ...options.headers };
  if (token) {
    headers["Authorization"] = `Token ${token}`;
  }
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
  }

  const res = await fetch(url, { ...options, headers });

  if (res.status === 401 || res.status === 403) {
    localStorage.removeItem("token");
    window.location.href = "/login";
    throw new Error("Authentication required");
  }

  if (!res.ok) {
    const data = await res.json().catch(() => null);
    const msg =
      data?.error || data?.errors || data?.detail || `Request failed (${res.status})`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }

  if (res.status === 204) return null;
  return res.json();
}

export function login(username, password) {
  return request("/api/auth/login/", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function uploadFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const formData = new FormData();
    formData.append("file", file);

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error(`Upload failed (${xhr.status})`));
      }
    });

    xhr.addEventListener("error", () => reject(new Error("Upload failed")));

    const token = localStorage.getItem("token");
    xhr.open("POST", `${BASE_URL}/api/products/import/`);
    if (token) xhr.setRequestHeader("Authorization", `Token ${token}`);
    xhr.send(formData);
  });
}

export function getImportStatus(id) {
  return request(`/api/products/import/${id}/`);
}

export function getJobStatus() {
  return request("/api/classification/jobs/status/");
}

export function getReviewList({ page = 1, search = "", minConfidence, maxConfidence } = {}) {
  const params = new URLSearchParams();
  params.set("page", page);
  if (search) params.set("search", search);
  if (minConfidence != null) params.set("min_confidence", minConfidence);
  if (maxConfidence != null) params.set("max_confidence", maxConfidence);
  return request(`/api/classification/review/?${params.toString()}`);
}

export function getReviewDetail(id) {
  return request(`/api/classification/review/${id}/`);
}

export function approveClassification(id) {
  return request(`/api/classification/review/${id}/approve/`, { method: "POST" });
}

export function correctClassification(id, { categoryId, attributes }) {
  const body = {};
  if (categoryId != null) body.category_id = categoryId;
  if (attributes != null) body.attributes = attributes;
  return request(`/api/classification/review/${id}/correct/`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function searchCategories(query) {
  return request(`/api/taxonomy/categories/?search=${encodeURIComponent(query)}`);
}
