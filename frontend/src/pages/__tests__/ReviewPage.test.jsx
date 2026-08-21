import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

vi.mock("../../api/client", () => ({
  getReviewList: vi.fn(),
  approveClassification: vi.fn(),
  correctClassification: vi.fn(),
  searchCategories: vi.fn(),
}));

import ReviewPage from "../ReviewPage";
import {
  getReviewList,
  approveClassification,
  correctClassification,
  searchCategories,
} from "../../api/client";

const mockItems = [
  {
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
    reviewed_at: null,
    correction_notes: "",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: 43,
    product: { id: 2, title: "Oak Dining Table", image_urls: [] },
    category: { id: 30, name: "Dining Tables", full_path: "Home > Dining Tables" },
    alternatives: [],
    attributes: [],
    confidence: 55.0,
    status: "needs_review",
    reviewed_at: null,
    correction_notes: "",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <ReviewPage />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  getReviewList.mockResolvedValue({ results: mockItems, count: 2 });
  approveClassification.mockResolvedValue({});
  correctClassification.mockResolvedValue({});
  searchCategories.mockResolvedValue([]);
});

describe("ReviewPage list rendering", () => {
  it("renders all queued products with categories and counts", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Red Leather Sofa")).toBeInTheDocument();
    });
    expect(screen.getByText("Oak Dining Table")).toBeInTheDocument();
    expect(screen.getByText("Home > Furniture > Sofas")).toBeInTheDocument();
    expect(screen.getByText("2 items")).toBeInTheDocument();
  });

  it("renders confidence badges per item", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("85%")).toBeInTheDocument();
    });
    expect(screen.getByText("55%")).toBeInTheDocument();
  });

  it("shows empty state when the queue is clear", async () => {
    getReviewList.mockResolvedValue({ results: [], count: 0 });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/No items need review/i)).toBeInTheDocument();
    });
  });

  it("paginates through results", async () => {
    getReviewList
      .mockResolvedValueOnce({ results: mockItems, count: 27 })
      .mockResolvedValueOnce({ results: [], count: 27 });
    renderPage();

    const next = await screen.findByText("Next");
    expect(screen.getByText("Previous").closest("button")).toBeDisabled();
    await userEvent.click(next);

    await waitFor(() => {
      expect(getReviewList).toHaveBeenLastCalledWith({ page: 2, search: "" });
    });
  });
});

describe("ReviewPage expand and resolve", () => {
  it("expands a row on click to show detail actions and alternatives", async () => {
    renderPage();
    const row = await screen.findByText("Red Leather Sofa");
    await userEvent.click(row);

    expect(await screen.findByText("Approve as-is")).toBeInTheDocument();
    expect(screen.getByText("Correct")).toBeInTheDocument();
    expect(screen.getByText("Alternatives")).toBeInTheDocument();
    expect(screen.getByText("Home > Furniture > Chairs")).toBeInTheDocument();
    expect(screen.getByText(/Color/)).toBeInTheDocument();
    expect(screen.getByText("Red")).toBeInTheDocument();
  });

  it("collapses the row when clicked again", async () => {
    renderPage();
    const row = await screen.findByText("Red Leather Sofa");
    await userEvent.click(row);
    expect(await screen.findByText("Approve as-is")).toBeInTheDocument();

    await userEvent.click(row);
    await waitFor(() => {
      expect(screen.queryByText("Approve as-is")).not.toBeInTheDocument();
    });
  });

  it("approving removes the item from the queue", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Red Leather Sofa"));
    await userEvent.click(await screen.findByText("Approve as-is"));

    await waitFor(() => {
      expect(approveClassification).toHaveBeenCalledWith(42);
    });
    await waitFor(() => {
      expect(screen.queryByText("Red Leather Sofa")).not.toBeInTheDocument();
    });
    expect(screen.getByText("1 items")).toBeInTheDocument();
  });

  it("submitting a correction sends category and attributes", async () => {
    searchCategories.mockResolvedValue([
      { id: 77, name: "Daybeds", full_path: "Home > Daybeds" },
    ]);
    renderPage();
    await userEvent.click(await screen.findByText("Red Leather Sofa"));
    await userEvent.click(screen.getByText("Correct"));

    // Category search input
    await userEvent.type(
      screen.getByPlaceholderText("Search category..."),
      "day"
    );
    const select = await screen.findByRole("combobox");
    await userEvent.selectOptions(select, "77");

    await userEvent.click(screen.getByText("Submit correction"));

    await waitFor(() => {
      expect(correctClassification).toHaveBeenCalledWith(42, {
        categoryId: 77,
        attributes: [
          { name: "Color", value: "Red" },
          { name: "Material", value: "Leather" },
        ],
      });
    });
    await waitFor(() => {
      expect(screen.queryByText("Red Leather Sofa")).not.toBeInTheDocument();
    });
  });
});
