import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EmptyState } from "./EmptyState";
import { Skeleton } from "./Skeleton";
import { StatusMark } from "./StatusMark";
import { ToastProvider, useToast, type ToastInput } from "./Toast";

function Trigger({ toast }: { toast: ToastInput }) {
  const { show } = useToast();
  return <button onClick={() => show(toast)}>show</button>;
}

afterEach(() => vi.useRealTimers());

describe("toasts", () => {
  it("announce their text in a polite live region", async () => {
    render(<ToastProvider><Trigger toast={{ text: "Saved 2 papers" }} /></ToastProvider>);
    await userEvent.click(screen.getByRole("button", { name: "show" }));
    expect(screen.getByRole("region", { name: "Notifications" })).toHaveTextContent("Saved 2 papers");
  });

  it("run their action once and close", async () => {
    const run = vi.fn();
    render(<ToastProvider><Trigger toast={{ text: "Saved", action: { label: "Undo", run } }} /></ToastProvider>);
    await userEvent.click(screen.getByRole("button", { name: "show" }));
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(run).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });

  it("disappear after their time", () => {
    vi.useFakeTimers();
    render(<ToastProvider><Trigger toast={{ text: "Bye", ms: 1000 }} /></ToastProvider>);
    act(() => screen.getByRole("button", { name: "show" }).click());
    expect(screen.getByText("Bye")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1100));
    expect(screen.queryByText("Bye")).not.toBeInTheDocument();
  });

  it("can be dismissed with the close button", async () => {
    render(<ToastProvider><Trigger toast={{ text: "Hello", tone: "bad" }} /></ToastProvider>);
    await userEvent.click(screen.getByRole("button", { name: "show" }));
    expect(screen.getByText(/Problem:/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("Hello")).not.toBeInTheDocument();
  });
});

describe("small pieces", () => {
  it("StatusMark shows an icon and a word", () => {
    render(<StatusMark status="relevant" />);
    expect(screen.getByText("Useful")).toBeInTheDocument();
    expect(screen.getByText("★")).toHaveAttribute("aria-hidden", "true");
  });

  it("Skeleton is busy and says what loads", () => {
    render(<Skeleton label="papers" />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Loading papers…")).toBeInTheDocument();
  });

  it("EmptyState teaches the next step", () => {
    render(<EmptyState title="Nothing saved yet" action={<a href="/">Go to Papers</a>}>Select papers and save them.</EmptyState>);
    expect(screen.getByText("Nothing saved yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to Papers" })).toBeInTheDocument();
  });
});
