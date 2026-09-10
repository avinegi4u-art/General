import { beforeEach, describe, expect, it } from "vitest";
import request from "supertest";
import { createApp } from "../src/app.js";
import { TaskStore } from "../src/store.js";

function makeApp() {
  return createApp(new TaskStore(":memory:"));
}

describe("Daily Tasks API", () => {
  let app: ReturnType<typeof makeApp>;

  beforeEach(() => {
    app = makeApp();
  });

  it("reports health", async () => {
    const res = await request(app).get("/api/health");
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: "ok" });
  });

  it("starts with no tasks", async () => {
    const res = await request(app).get("/api/tasks");
    expect(res.status).toBe(200);
    expect(res.body).toEqual([]);
  });

  it("creates a task", async () => {
    const res = await request(app).post("/api/tasks").send({ title: "Buy milk" });
    expect(res.status).toBe(201);
    expect(res.body).toMatchObject({ title: "Buy milk", completed: false });
    expect(res.body.id).toBeTruthy();
    expect(res.body.createdAt).toBeTruthy();
  });

  it("rejects an empty title", async () => {
    const res = await request(app).post("/api/tasks").send({ title: "   " });
    expect(res.status).toBe(400);
  });

  it("toggles completion", async () => {
    const created = await request(app).post("/api/tasks").send({ title: "Walk dog" });
    const id = created.body.id;
    const patched = await request(app).patch(`/api/tasks/${id}`).send({ completed: true });
    expect(patched.status).toBe(200);
    expect(patched.body.completed).toBe(true);
  });

  it("updates a title", async () => {
    const created = await request(app).post("/api/tasks").send({ title: "Old" });
    const patched = await request(app)
      .patch(`/api/tasks/${created.body.id}`)
      .send({ title: "New" });
    expect(patched.body.title).toBe("New");
  });

  it("returns 404 when updating a missing task", async () => {
    const res = await request(app).patch("/api/tasks/does-not-exist").send({ completed: true });
    expect(res.status).toBe(404);
  });

  it("deletes a task", async () => {
    const created = await request(app).post("/api/tasks").send({ title: "Temp" });
    const del = await request(app).delete(`/api/tasks/${created.body.id}`);
    expect(del.status).toBe(204);
    const list = await request(app).get("/api/tasks");
    expect(list.body).toEqual([]);
  });

  it("returns 404 when deleting a missing task", async () => {
    const res = await request(app).delete("/api/tasks/nope");
    expect(res.status).toBe(404);
  });

  it("lists newest tasks first", async () => {
    await request(app).post("/api/tasks").send({ title: "first" });
    await new Promise((r) => setTimeout(r, 5));
    await request(app).post("/api/tasks").send({ title: "second" });
    const res = await request(app).get("/api/tasks");
    expect(res.body.map((t: { title: string }) => t.title)).toEqual(["second", "first"]);
  });
});
