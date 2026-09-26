import { render, screen } from "@testing-library/react";

import { App } from "./App";

it("renders the app title", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "Research Agent" })).toBeInTheDocument();
});
