import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { createApp } from "./app.js";
import { TaskStore } from "./store.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT ?? 3001);
const DATA_FILE = process.env.DATA_FILE ?? resolve(__dirname, "../data/tasks.json");

const store = new TaskStore(DATA_FILE);
const app = createApp(store);

app.listen(PORT, () => {
  console.log(`[server] Daily Tasks API listening on http://localhost:${PORT}`);
  console.log(`[server] Persisting tasks to ${DATA_FILE}`);
});
