import { cursorGreater } from "./events";

test("cursors compare numerically, not lexically", () => {
  expect(cursorGreater("10", "9")).toBe(true);
  expect(cursorGreater("9", "10")).toBe(false);
  expect(cursorGreater("12345678901234567890", "12345678901234567889")).toBe(true);
  expect(cursorGreater("5", "5")).toBe(false);
});
