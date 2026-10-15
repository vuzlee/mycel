import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Modal } from "./Modal";

describe("Modal", () => {
  it("takes focus, keeps Tab inside and gives focus back", () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const { unmount } = render(
      <Modal title="T" onClose={vi.fn()}>
        <button>Inner</button>
      </Modal>,
    );
    expect(document.activeElement).toBe(screen.getByRole("dialog"));
    screen.getByText("Inner").focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(screen.getByLabelText("Close"));
    unmount();
    expect(document.activeElement).toBe(opener);
  });
});
