import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const pluginRoot = resolve(packageRoot, "plugins", "interview-growth");

async function runHook(
	pi: ExtensionAPI,
	command: "healthcheck" | "checkpoint",
	options?: { sessionId?: string; event?: string },
) {
	const args = [
		"run",
		"--locked",
		"--no-editable",
		"--project",
		pluginRoot,
		"python",
		"-m",
		"interview_growth.hook_cli",
		command,
	];
	if (options?.sessionId) args.push("--session-id", options.sessionId);
	if (options?.event) args.push("--event", options.event);
	return pi.exec("uv", args, { cwd: pluginRoot, timeout: 120_000 });
}

function bindSession(ctx: ExtensionContext): string {
	const sessionId = ctx.sessionManager.getSessionId();
	process.env.INTERVIEW_GROWTH_SESSION_ID = sessionId;
	return sessionId;
}

export default function (pi: ExtensionAPI) {
	pi.on("session_start", async (_event, ctx) => {
		bindSession(ctx);
		const result = await runHook(pi, "healthcheck");
		if (result.code !== 0 && ctx.hasUI) {
			ctx.ui.notify(
				`Interview Growth storage check failed: ${result.stderr.trim() || "unknown error"}`,
				"error",
			);
		}
	});

	pi.on("before_agent_start", (event, ctx) => {
		const sessionId = bindSession(ctx);
		return {
			systemPrompt:
				event.systemPrompt +
				`\n\nInterview Growth host session ID: ${sessionId}. ` +
				"Use this exact value for every interview-growth CLI session_id in this Pi session.",
		};
	});

	pi.on("session_before_compact", async (event, ctx) => {
		const sessionId = bindSession(ctx);
		await runHook(pi, "checkpoint", {
			sessionId,
			event: `pi:${event.reason}`,
		});
	});

	pi.on("session_shutdown", (_event, ctx) => {
		const sessionId = ctx.sessionManager.getSessionId();
		if (process.env.INTERVIEW_GROWTH_SESSION_ID === sessionId) {
			delete process.env.INTERVIEW_GROWTH_SESSION_ID;
		}
	});
}
