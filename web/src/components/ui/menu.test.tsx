import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "./ConfirmDialog";
import { MenuButton } from "./MenuButton";

describe("menu button", () => {
  it("opens with the keyboard, skips disabled items, chooses and returns focus", async () => {
    const open = vi.fn();
    const remove = vi.fn();
    render(<MenuButton label="Actions" items={[
      { label: "Open", onSelect: open },
      { label: "Resume", onSelect: vi.fn(), disabled: true },
      { label: "Delete", onSelect: remove, danger: true },
    ]} />);
    const trigger = screen.getByRole("button", { name: "Actions" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    trigger.focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menuitem", { name: "Open" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Delete" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(remove).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("closes on Escape without choosing", async () => {
    const open = vi.fn();
    render(<MenuButton label="Actions" items={[{ label: "Open", onSelect: open }]} />);
    await userEvent.click(screen.getByRole("button", { name: "Actions" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(open).not.toHaveBeenCalled();
  });
});

describe("confirm dialog", () => {
  it("starts on Cancel, keeps Tab inside and cancels on Escape", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<ConfirmDialog title="Delete 2 runs?" confirmLabel="Delete" onConfirm={onConfirm} onCancel={onCancel}>Folders move to the trash.</ConfirmDialog>);
    const dialog = screen.getByRole("alertdialog", { name: "Delete 2 runs?" });
    expect(dialog).toHaveAccessibleDescription("Folders move to the trash.");
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Delete" })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
