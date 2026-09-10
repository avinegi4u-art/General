import type { Task } from "./types";

export type Filter = "all" | "active" | "completed";

export function filterTasks(tasks: Task[], filter: Filter): Task[] {
  switch (filter) {
    case "active":
      return tasks.filter((task) => !task.completed);
    case "completed":
      return tasks.filter((task) => task.completed);
    default:
      return tasks;
  }
}

export function remainingCount(tasks: Task[]): number {
  return tasks.filter((task) => !task.completed).length;
}
