import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { isTypingTarget, useShortcuts } from "./shortcuts";
import { ShortcutsHelp } from "./ShortcutsHelp";

function Probe({ onJ }: { onJ: () => void }) {
  const [help, setHelp] = useState(false);
  useShortcuts({ j: onJ, "?": () => setHelp(true) });
  return (
    <>
      <input aria-label="search" />
      <button>opener</button>
      {help && <ShortcutsHelp title="Keyboard shortcuts" items={[{ keys: ["j"], what: "Next paper" }]} onClose={() => setHelp(false)} />}
    </>
  );
}

describe("shortcuts", () => {
  it("run on a plain key press", async () => {
    const onJ = vi.fn();
    render(<Probe onJ={onJ} />);
    await userEvent.keyboard("j");
    expect(onJ).toHaveBeenCalledTimes(1);
  });

  it("never fire while typing in a field", async () => {
    const onJ = vi.fn();
    render(<Probe onJ={onJ} />);
    await userEvent.type(screen.getByLabelText("search"), "jjj");
    expect(onJ).not.toHaveBeenCalled();
    expect(screen.getByLabelText("search")).toHaveValue("jjj");
  });

  it("ignore keys held with Ctrl, Meta or Alt", () => {
    const onJ = vi.fn();
    render(<Probe onJ={onJ} />);
    fireEvent.keyDown(document.body, { key: "j", ctrlKey: true });
    fireEvent.keyDown(document.body, { key: "j", metaKey: true });
    fireEvent.keyDown(document.body, { key: "j", altKey: true });
    expect(onJ).not.toHaveBeenCalled();
  });

  it("? opens a labelled help sheet; Close returns focus", async () => {
    render(<Probe onJ={vi.fn()} />);
    screen.getByRole("button", { name: "opener" }).focus();
    await userEvent.keyboard("?");
    const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
    expect(dialog).toHaveTextContent("Next paper");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "opener" })).toHaveFocus();
  });

  it("knows what a typing target is", () => {
    expect(isTypingTarget(document.createElement("textarea"))).toBe(true);
    expect(isTypingTarget(document.createElement("button"))).toBe(false);
  });
});
