import { OWNER_ID, OWNER_POS, arc, hexToRgb, layout, lookAt, multiply, perspective, project, ringRadius } from "./chartMath";

test("layout puts the owner at the centre and each level on its own ring", () => {
  const pos = layout([{ id: "a", levelIndex: 0 }, { id: "b", levelIndex: 1 }, { id: "c", levelIndex: 1 }]);
  expect(pos.get(OWNER_ID)).toEqual(OWNER_POS);
  const r = (id: string) => Math.hypot(pos.get(id)![0], pos.get(id)![2]);
  expect(r("a")).toBeCloseTo(ringRadius(0));
  expect(r("b")).toBeCloseTo(ringRadius(1));
  expect(r("c")).toBeCloseTo(ringRadius(1));
  expect(pos.get("b")).not.toEqual(pos.get("c"));
});

test("arcs start and end at their stations and rise in between", () => {
  const { points, t } = arc([0, 0, 0], [2, 0, 0], 10);
  expect(points[0]).toEqual([0, 0, 0]);
  expect(points[10][0]).toBeCloseTo(2);
  expect(points[5][1]).toBeGreaterThan(0.3);
  expect(t[10]).toBe(1);
});

test("the camera projects the target to the centre of the view", () => {
  const vp = multiply(perspective(0.8, 2, 0.1, 100), lookAt([0, 3, 6], [0, 0, 0], [0, 1, 0]));
  const c = project(vp, [0, 0, 0], 800, 400)!;
  expect(c.x).toBeCloseTo(400);
  expect(c.y).toBeCloseTo(200);
  expect(project(vp, [0, 30, 60], 800, 400)).toBeNull();
});

test("hex colours parse to unit rgb", () => {
  expect(hexToRgb("#ff0000")).toEqual([1, 0, 0]);
  expect(hexToRgb(" #1f4f8f ")[2]).toBeCloseTo(0x8f / 255);
});
