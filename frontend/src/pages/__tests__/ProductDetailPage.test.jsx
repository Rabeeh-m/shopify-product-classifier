import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

vi.mock("../../api/client", () => ({
  getClassifiedProductDetail: vi.fn(),
}));

import { getClassifiedProductDetail } from "../../api/client";
import ProductDetailPage from "../ProductDetailPage";

const mockDetail = {
  id: 42,
  product: {
    id: 1,
    title: "Red Leather Sofa",
    description: "A comfortable leather sofa.",
    brand: "Acme",
    product_type: "Sofa",
    external_id: "sku-001",
    raw_data: { color: "Red", material: "Leather" },
    status: "done",
    error_message: "",
    images: ["http://example.com/sofa.jpg"],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
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
  source: "AI",
  reviewed_by: null,
  reviewed_at: null,
  correction_notes: "",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

function renderPage(id = "42") {
  return render(
    <MemoryRouter initialEntries={[`/products/${id}`]}>
      <Routes>
        <Route path="/products/:id" element={<ProductDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ProductDetailPage", () => {
  it("renders product details", async () => {
    getClassifiedProductDetail.mockResolvedValue(mockDetail);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Red Leather Sofa")).toBeInTheDocument();
    });
    expect(screen.getByText("Home > Furniture > Sofas")).toBeInTheDocument();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("A comfortable leather sofa.")).toBeInTheDocument();
    expect(getClassifiedProductDetail).toHaveBeenCalledWith("42");
  });

  it("renders attributes and source data tables", async () => {
    getClassifiedProductDetail.mockResolvedValue(mockDetail);
    renderPage();

    expect(await screen.findByText("Attributes")).toBeInTheDocument();
    expect(screen.getByText("Color")).toBeInTheDocument();
    expect(screen.getByText("Source Data")).toBeInTheDocument();
    expect(screen.getByText("material")).toBeInTheDocument();
  });

  it("shows error state when fetch fails", async () => {
    getClassifiedProductDetail.mockRejectedValue(new Error("Product not found"));
    renderPage("999");

    await waitFor(() => {
      expect(screen.getByText("Product not found")).toBeInTheDocument();
    });
    expect(screen.getByText("Back to products")).toBeInTheDocument();
  });
});