import { render, screen } from "@testing-library/react";
import { DeliveryState } from "./AgentsPage";

test("a completed notification reads 'notified', never as success", () => {
  render(<DeliveryState d={{ purpose: "notification", state: "completed" }} />);
  expect(screen.getByText("notified")).toBeInTheDocument();
  expect(screen.queryByText("completed")).toBeNull();
});

test("a failed notification keeps its real outcome", () => {
  render(<DeliveryState d={{ purpose: "notification", state: "failed" }} />);
  expect(screen.getByText("failed").className).toContain("pill--bad");
});

test("tasks are unchanged", () => {
  render(<DeliveryState d={{ purpose: "task", state: "completed" }} />);
  expect(screen.getByText("completed").className).toContain("pill--ok");
});
