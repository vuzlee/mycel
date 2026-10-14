import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const destroyed = vi.fn(async () => {});
let resolveDoc: (doc: unknown) => void = () => {};

vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerSrc: "" },
  getDocument: () => ({
    promise: new Promise((resolve) => {
      resolveDoc = resolve;
    }),
    destroy: destroyed,
  }),
  Util: { applyTransform: (p: number[]) => p },
}));
vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({ default: "worker.js" }));

import { PdfPage } from "./PdfPage";

afterEach(() => destroyed.mockClear());

describe("PdfPage", () => {
  it("destroys the loading task, and so its worker, when it closes", async () => {
    const view = render(<PdfPage url="/doc.pdf" first={1} last={1} quote="x" />);
    await vi.waitFor(() => expect(resolveDoc).not.toBe(undefined));
    await new Promise((resolve) => setTimeout(resolve, 0));

    view.unmount();

    expect(destroyed).toHaveBeenCalledTimes(1);
  });
});
