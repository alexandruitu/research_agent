import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { GlossaryLink, GlossaryProvider } from "./GlossaryDialog";
import { GLOSSARY, GLOSSARY_KEYS } from "./terms";
import { Term } from "./Term";

describe("Term", () => {
  it("shows the word and describes it from the glossary on focus", async () => {
    render(<p><Term k="kappa" /></p>);
    expect(screen.getByText("kappa")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "What is “kappa”?" });
    expect(screen.queryByRole("tooltip")).toBeNull();
    await userEvent.tab();
    expect(button).toHaveFocus();
    const tip = screen.getByRole("tooltip");
    expect(button).toHaveAttribute("aria-describedby", tip.id);
    expect(tip).toHaveTextContent(GLOSSARY.kappa.text);
  });

  it("toggles on click or tap and closes with Escape", async () => {
    render(<Term k="jev">Jev</Term>);
    const button = screen.getByRole("button", { name: /Jev/ });
    fireEvent.click(button);
    expect(screen.getByRole("tooltip")).toBeVisible();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("closes when the user taps elsewhere", () => {
    render(<><Term k="recall" /><p>elsewhere</p></>);
    fireEvent.click(screen.getByRole("button", { name: /recall/ }));
    fireEvent.pointerDown(screen.getByText("elsewhere"));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});

describe("Glossary", () => {
  it("lists every term, sorted, in a dialog", async () => {
    render(<GlossaryProvider><GlossaryLink /></GlossaryProvider>);
    await userEvent.click(screen.getByRole("button", { name: "Glossary" }));
    const dialog = screen.getByRole("dialog", { name: "Glossary" });
    const terms = [...dialog.querySelectorAll("dt")].map((dt) => dt.textContent);
    expect(terms).toEqual(GLOSSARY_KEYS.map((k) => GLOSSARY[k].label));
    expect(terms).toContain("Fleiss kappa");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
