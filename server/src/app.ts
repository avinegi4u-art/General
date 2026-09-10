import cors from "cors";
import express, { type Express } from "express";
import { TaskStore } from "./store.js";

export function createApp(store: TaskStore): Express {
  const app = express();
  app.use(cors());
  app.use(express.json());

  app.get("/api/health", (_req, res) => {
    res.json({ status: "ok" });
  });

  app.get("/api/tasks", (_req, res) => {
    res.json(store.list());
  });

  app.post("/api/tasks", (req, res) => {
    const title = typeof req.body?.title === "string" ? req.body.title.trim() : "";
    if (!title) {
      res.status(400).json({ error: "title is required" });
      return;
    }
    const task = store.create({ title });
    res.status(201).json(task);
  });

  app.patch("/api/tasks/:id", (req, res) => {
    const { title, completed } = req.body ?? {};
    if (title !== undefined && typeof title !== "string") {
      res.status(400).json({ error: "title must be a string" });
      return;
    }
    if (completed !== undefined && typeof completed !== "boolean") {
      res.status(400).json({ error: "completed must be a boolean" });
      return;
    }
    if (typeof title === "string" && title.trim() === "") {
      res.status(400).json({ error: "title cannot be empty" });
      return;
    }
    const task = store.update(req.params.id, { title, completed });
    if (!task) {
      res.status(404).json({ error: "task not found" });
      return;
    }
    res.json(task);
  });

  app.delete("/api/tasks/:id", (req, res) => {
    const removed = store.remove(req.params.id);
    if (!removed) {
      res.status(404).json({ error: "task not found" });
      return;
    }
    res.status(204).end();
  });

  return app;
}
