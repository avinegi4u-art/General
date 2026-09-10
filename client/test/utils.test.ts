import { describe, expect, it } from "vitest";
import { filterTasks, remainingCount } from "../src/utils";
import type { Task } from "../src/types";

const tasks: Task[] = [
  { id: "1", title: "a", completed: false, createdAt: "2026-01-01T00:00:00Z" },
  { id: "2", title: "b", completed: true, createdAt: "2026-01-02T00:00:00Z" },
  { id: "3", title: "c", completed: false, createdAt: "2026-01-03T00:00:00Z" },
];

describe("filterTasks", () => {
  it("returns all tasks for 'all'", () => {
    expect(filterTasks(tasks, "all")).toHaveLength(3);
  });

  it("returns only active tasks", () => {
    expect(filterTasks(tasks, "active").map((t) => t.id)).toEqual(["1", "3"]);
  });

  it("returns only completed tasks", () => {
    expect(filterTasks(tasks, "completed").map((t) => t.id)).toEqual(["2"]);
  });
});

describe("remainingCount", () => {
  it("counts active tasks", () => {
    expect(remainingCount(tasks)).toBe(2);
  });
});
