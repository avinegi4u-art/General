import { useEffect, useMemo, useState } from "react";
import { createTask, deleteTask, fetchTasks, updateTask } from "./api";
import type { Task } from "./types";
import { filterTasks, remainingCount, type Filter } from "./utils";

const FILTERS: Filter[] = ["all", "active", "completed"];

export function App() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [title, setTitle] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchTasks()
      .then(setTasks)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const visibleTasks = useMemo(() => filterTasks(tasks, filter), [tasks, filter]);
  const remaining = useMemo(() => remainingCount(tasks), [tasks]);

  async function handleAdd(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) return;
    setError(null);
    try {
      const created = await createTask(trimmed);
      setTasks((prev) => [created, ...prev]);
      setTitle("");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function handleToggle(task: Task) {
    try {
      const updated = await updateTask(task.id, { completed: !task.completed });
      setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteTask(id);
      setTasks((prev) => prev.filter((t) => t.id !== id));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <main className="app">
      <header className="app__header">
        <h1>Daily Tasks</h1>
        <p className="app__subtitle">
          {remaining} {remaining === 1 ? "task" : "tasks"} to go
        </p>
      </header>

      <form className="task-form" onSubmit={handleAdd}>
        <input
          className="task-form__input"
          type="text"
          placeholder="What needs doing today?"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          aria-label="New task title"
        />
        <button className="task-form__button" type="submit">
          Add
        </button>
      </form>

      {error && <p className="app__error" role="alert">{error}</p>}

      <div className="filters" role="tablist" aria-label="Filter tasks">
        {FILTERS.map((f) => (
          <button
            key={f}
            role="tab"
            aria-selected={filter === f}
            className={`filters__button ${filter === f ? "is-active" : ""}`}
            onClick={() => setFilter(f)}
          >
            {f[0].toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="app__empty">Loading…</p>
      ) : visibleTasks.length === 0 ? (
        <p className="app__empty">Nothing here yet. Add your first task above.</p>
      ) : (
        <ul className="task-list">
          {visibleTasks.map((task) => (
            <li key={task.id} className={`task ${task.completed ? "is-done" : ""}`}>
              <label className="task__label">
                <input
                  type="checkbox"
                  checked={task.completed}
                  onChange={() => handleToggle(task)}
                  aria-label={`Mark "${task.title}" as ${task.completed ? "active" : "completed"}`}
                />
                <span className="task__title">{task.title}</span>
              </label>
              <button
                className="task__delete"
                onClick={() => handleDelete(task.id)}
                aria-label={`Delete "${task.title}"`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
