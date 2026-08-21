import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../../api/client", () => ({
  uploadFile: vi.fn(),
  getImportStatus: vi.fn(),
  getLatestImport: vi.fn(),
  getJobStatus: vi.fn(),
}));

import UploadPage from "../UploadPage";
import {
  getImportStatus,
  getLatestImport,
  getJobStatus,
} from "../../api/client";

const doneJobs = {
  total: 3,
  pending: 0,
  processing: 0,
  done: 2,
  needs_review: 1,
  failed: 0,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <UploadPage />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("UploadPage state restoration", () => {
  it("restores the last import summary when returning to the page", async () => {
    getLatestImport.mockResolvedValue({
      id: 21,
      status: "completed",
      total_rows: 4999,
      imported_rows: 4999,
      failed_rows: 0,
    });
    getJobStatus.mockResolvedValue(doneJobs);

    renderPage();

    expect(await screen.findByText("Import #21")).toBeInTheDocument();
    expect(screen.getByText(/4999 rows inserted/i)).toBeInTheDocument();
    // Status grid restored too
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.getByText("Needs Review")).toBeInTheDocument();
  });

  it("shows nothing stale when there are no imports yet", async () => {
    getLatestImport.mockRejectedValue(new Error("No imports yet."));

    renderPage();

    await act(async () => {});
    expect(screen.queryByText(/Import #/)).not.toBeInTheDocument();
  });

  it("resumes polling when the restored import is still processing", async () => {
    vi.useFakeTimers();
    const processing = {
      id: 22,
      status: "processing",
      total_rows: 10,
      imported_rows: 4,
      failed_rows: 0,
    };
    getLatestImport.mockResolvedValue(processing);
    getJobStatus.mockResolvedValue({
      ...doneJobs,
      total: 10,
      pending: 6,
      processing: 0,
      done: 4,
    });
    getImportStatus.mockResolvedValue({ ...processing, imported_rows: 5 });

    renderPage();
    await act(async () => {});

    expect(getImportStatus).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(getImportStatus).toHaveBeenCalledWith(22);
  });
});
