import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const run = promisify(execFile);

function render(bundle) {
  const items = [...(bundle.mandatory_policies || []), ...(bundle.curated_memory || [])];
  if (!items.length) return "";
  return ["<docmancer-context>", ...items.map((item) => `## ${item.title}\n${item.excerpt}\nSource: ${item.address}`), "</docmancer-context>"].join("\n\n");
}

export default definePluginEntry({
  id: "docmancer",
  name: "Docmancer",
  description: "Inject bounded local Docmancer context before model calls.",
  register(api) {
    api.on("before_prompt_build", async (event, ctx) => {
      const task = typeof event.prompt === "string" ? event.prompt.trim() : "";
      if (!task) return;
      const config = event.context?.pluginConfig || {};
      const budget = Math.min(10000, Math.max(100, Number(config.tokenBudget || 2000)));
      const cwd = ctx.workspaceDir || process.cwd();
      try {
        const { stdout } = await run("docmancer", ["context", task.slice(0, 8000), "--project-path", cwd, "--token-budget", String(budget), "--json"], { cwd, timeout: 3000, maxBuffer: 1024 * 1024 });
        const context = render(JSON.parse(stdout));
        if (context) return { prependContext: context };
      } catch {
        return;
      }
    }, { priority: 20, timeoutMs: 3500 });
  }
});
