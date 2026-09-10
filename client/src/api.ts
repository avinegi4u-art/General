import type { Task } from "./types";

const BASE = "/api/tasks";

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const message = await res.text().catch(() => res.statusText);
    throw new Error(message || `Request failed with ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchTasks(): Promise<Task[]> {
  return parse<Task[]>(await fetch(BASE));
}

export async function createTask(title: string): Promise<Task> {
  return parse<Task>(
    await fetch(BASE, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  );
}

export async function updateTask(
  id: string,
  patch: { title?: string; completed?: boolean },
): Promise<Task> {
  return parse<Task>(
    await fetch(`${BASE}/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  );
}

export async function deleteTask(id: string): Promise<void> {
  const res = await fetch(`${BASE}/${id}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`Failed to delete task (${res.status})`);
  }
}
