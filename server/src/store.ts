import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { CreateTaskInput, Task, UpdateTaskInput } from "./types.js";

/**
 * A tiny file-backed task store. Persistence uses a JSON file so that the
 * data survives server restarts during development. Passing ":memory:" keeps
 * everything in memory, which is what the automated tests use.
 */
export class TaskStore {
  private tasks: Task[] = [];
  private readonly filePath: string | null;

  constructor(filePath: string) {
    this.filePath = filePath === ":memory:" ? null : filePath;
    this.load();
  }

  private load(): void {
    if (!this.filePath) return;
    if (!existsSync(this.filePath)) {
      this.tasks = [];
      return;
    }
    try {
      const raw = readFileSync(this.filePath, "utf-8");
      const parsed = JSON.parse(raw) as Task[];
      this.tasks = Array.isArray(parsed) ? parsed : [];
    } catch {
      this.tasks = [];
    }
  }

  private persist(): void {
    if (!this.filePath) return;
    mkdirSync(dirname(this.filePath), { recursive: true });
    writeFileSync(this.filePath, JSON.stringify(this.tasks, null, 2), "utf-8");
  }

  list(): Task[] {
    return [...this.tasks].sort((a, b) =>
      a.createdAt < b.createdAt ? 1 : a.createdAt > b.createdAt ? -1 : 0,
    );
  }

  get(id: string): Task | undefined {
    return this.tasks.find((task) => task.id === id);
  }

  create(input: CreateTaskInput): Task {
    const task: Task = {
      id: randomUUID(),
      title: input.title.trim(),
      completed: false,
      createdAt: new Date().toISOString(),
    };
    this.tasks.push(task);
    this.persist();
    return task;
  }

  update(id: string, input: UpdateTaskInput): Task | undefined {
    const task = this.get(id);
    if (!task) return undefined;
    if (typeof input.title === "string") task.title = input.title.trim();
    if (typeof input.completed === "boolean") task.completed = input.completed;
    this.persist();
    return task;
  }

  remove(id: string): boolean {
    const index = this.tasks.findIndex((task) => task.id === id);
    if (index === -1) return false;
    this.tasks.splice(index, 1);
    this.persist();
    return true;
  }
}
