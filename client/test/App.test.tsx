import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../src/App";
import type { Task } from "../src/types";

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: crypto.randomUUID(),
    title: "Sample",
    completed: false,
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("<App />", () => {
  let store: Task[];

  beforeEach(() => {
    store = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        const method = init?.method ?? "GET";

        if (url.endsWith("/api/tasks") && method === "GET") {
          return new Response(JSON.stringify(store), { status: 200 });
        }
        if (url.endsWith("/api/tasks") && method === "POST") {
          const body = JSON.parse(String(init?.body));
          const task = makeTask({ title: body.title });
          store = [task, ...store];
          return new Response(JSON.stringify(task), { status: 201 });
        }
        return new Response("not found", { status: 404 });
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows the empty state, then adds a task", async () => {
    render(<App />);

    expect(
      await screen.findByText(/Nothing here yet/i),
    ).toBeInTheDocument();

    const input = screen.getByLabelText(/new task title/i);
    await userEvent.type(input, "Water the plants");
    await userEvent.click(screen.getByRole("button", { name: /add/i }));

    await waitFor(() => {
      expect(screen.getByText("Water the plants")).toBeInTheDocument();
    });
  });
});
