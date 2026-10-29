import { render, screen } from "@testing-library/react";
import { App } from "./App";

test("renders the shell with navigation", () => {
  render(<App />);
  expect(screen.getByText("MAS")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Control room" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Projects" })).toBeInTheDocument();
});
