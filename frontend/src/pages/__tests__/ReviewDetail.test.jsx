import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ id: "42" }),
  };
});

vi.mock("../../api/client", () => ({
  getReviewDetail: vi.fn(),
  approveClassification: vi.fn(),
  correctClassification: vi.fn(),
}));

const mockClassification = {
  id: 42,
  product: {
    id: 1,
    title: "Red Leather Sofa",
    image_urls: ["http://example.com/sofa.jpg"],
  },
  category: { id: 15, name: "Sofas", full_path: "Home > Furniture > Sofas" },
  alternatives: [
    {
      category_id: 20,
      category: { id: 20, name: "Chairs", full_path: "Home > Furniture > Chairs" },
      confidence: 60.0,
    },
  ],
  attributes: [
    { attribute_name: "Color", value_display: "Red", free_text_value: "" },
    { attribute_name: "Material", value_display: "", free_text_value: "Leather" },
  ],
  confidence: 85.0,
  status: "needs_review",
  reviewed_by: null,
  reviewed_at: null,
  correction_notes: "",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

let getReviewDetail, approveClassification, correctClassification;

beforeEach(async () => {
  vi.clearAllMocks();
  const api = await import("../../api/client");
  getReviewDetail = api.getReviewDetail;
  approveClassification = api.approveClassification;
  correctClassification = api.correctClassification;
  getReviewDetail.mockResolvedValue(mockClassification);
});

import ReviewDetail from "../ReviewDetail";

function renderWithRouter(ui) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe("ReviewDetail", () => {
  it("renders product title and category", async () => {
    renderWithRouter(<ReviewDetail />);
    await waitFor(() => {
      expect(screen.getByText("Red Leather Sofa")).toBeInTheDocument();
    });
    expect(screen.getByText("Home > Furniture > Sofas")).toBeInTheDocument();
  });

  it("renders confidence badge", async () => {
    renderWithRouter(<ReviewDetail />);
    await waitFor(() => {
      expect(screen.getByText("85% confidence")).toBeInTheDocument();
    });
  });

  it("renders alternatives", async () => {
    renderWithRouter(<ReviewDetail />);
    await waitFor(() => {
      expect(screen.getByText("Home > Furniture > Chairs")).toBeInTheDocument();
    });
  });

  it("renders attributes", async () => {
    renderWithRouter(<ReviewDetail />);
    await waitFor(() => {
      expect(screen.getByText("Color")).toBeInTheDocument();
    });
    expect(screen.getByText("Red")).toBeInTheDocument();
    expect(screen.getByText("Leather")).toBeInTheDocument();
  });

  it("approve calls API and navigates", async () => {
    approveClassification.mockResolvedValue({ ...mockClassification, status: "approved" });
    const user = userEvent.setup();
    renderWithRouter(<ReviewDetail />);
    await waitFor(() => {
      expect(screen.getByText("Red Leather Sofa")).toBeInTheDocument();
    });
    await user.click(screen.getByText("Approve as-is"));
    expect(approveClassification).toHaveBeenCalledWith(42);
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/review");
    });
  });

  it("shows correct form on click", async () => {
    const user = userEvent.setup();
    renderWithRouter(<ReviewDetail />);
    await waitFor(() => {
      expect(screen.getByText("Red Leather Sofa")).toBeInTheDocument();
    });
    await user.click(screen.getByText("Correct"));
    expect(screen.getByText("Submit correction")).toBeInTheDocument();
  });

  it("correct sends attributes", async () => {
    correctClassification.mockResolvedValue({
      ...mockClassification,
      status: "approved",
    });
    const user = userEvent.setup();
    renderWithRouter(<ReviewDetail />);
    await waitFor(() => {
      expect(screen.getByText("Red Leather Sofa")).toBeInTheDocument();
    });
    await user.click(screen.getByText("Correct"));
    await user.click(screen.getByText("Submit correction"));
    expect(correctClassification).toHaveBeenCalledWith(42, {
      categoryId: undefined,
      attributes: [
        { name: "Color", value: "Red" },
        { name: "Material", value: "Leather" },
      ],
    });
  });

  it("shows error on API failure", async () => {
    approveClassification.mockRejectedValue(new Error("Already reviewed"));
    const user = userEvent.setup();
    renderWithRouter(<ReviewDetail />);
    await waitFor(() => {
      expect(screen.getByText("Red Leather Sofa")).toBeInTheDocument();
    });
    await user.click(screen.getByText("Approve as-is"));
    await waitFor(() => {
      expect(screen.getByText("Already reviewed")).toBeInTheDocument();
    });
  });
});
