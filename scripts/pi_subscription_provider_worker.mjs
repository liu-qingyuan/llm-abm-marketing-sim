#!/usr/bin/env node

import process from "node:process";
import { pathToFileURL } from "node:url";

const packageRoot = process.env.PI_CODING_AGENT_PACKAGE_ROOT;
if (!packageRoot) {
  throw new Error("PI_CODING_AGENT_PACKAGE_ROOT is required");
}

const rootUrl = pathToFileURL(`${packageRoot.replace(/\/$/, "")}/dist/`).href;
const { ModelRuntime, SettingsManager } = await import(`${rootUrl}index.js`);
const { applyHttpProxySettings, configureHttpDispatcher } = await import(
  `${rootUrl}core/http-dispatcher.js`
);

const settings = SettingsManager.create(process.cwd(), process.env.PI_AGENT_DIR);
applyHttpProxySettings(settings.getGlobalSettings().httpProxy);
configureHttpDispatcher(settings.getHttpIdleTimeoutMs());
const runtime = await ModelRuntime.create();

const modelAliases = Object.freeze({
  "gpt-5.4-mini": "gpt-5.4-mini",
  "gpt-5.4-2026-03-05": "gpt-5.4",
  "gpt-5.5-2026-04-23": "gpt-5.5",
  "gpt-5.6-sol": "gpt-5.6-sol",
});

const decisionFormat = Object.freeze({
  type: "json_schema",
  name: "engage_decision",
  strict: true,
  schema: {
    type: "object",
    additionalProperties: false,
    required: ["engage", "probability", "reason", "confidence", "action"],
    properties: {
      engage: { type: "boolean" },
      probability: { type: "number", minimum: 0, maximum: 1 },
      reason: { type: "string" },
      confidence: { type: "number", minimum: 0, maximum: 1 },
      action: { type: "string", enum: ["ignore", "like", "comment", "share"] },
    },
  },
});

function emit(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function safeError(error) {
  const name = error instanceof Error ? error.name : "Error";
  const message = error instanceof Error ? error.message : String(error);
  return `${name}: ${message}`.slice(0, 500);
}

function textContent(message) {
  return message.content
    .filter((item) => item.type === "text")
    .map((item) => item.text)
    .join("");
}

async function status(command) {
  const auth = await runtime.checkAuth("openai-codex");
  const models = Object.values(modelAliases).filter((id) => runtime.getModel("openai-codex", id));
  return {
    id: command.id,
    ok: Boolean(auth) && models.length === Object.keys(modelAliases).length,
    provider: "openai-codex",
    auth_type: auth?.type ?? null,
    models,
    requested_model_aliases: modelAliases,
  };
}

async function request(command) {
  const requestedModel = String(command.model ?? "");
  const upstreamModel = modelAliases[requestedModel];
  if (!upstreamModel) {
    throw new Error(`unsupported requested model: ${requestedModel}`);
  }
  if (command.reasoning_effort !== "low") {
    throw new Error("subscription robustness requests require reasoning_effort=low");
  }
  const outputCeiling = Number(command.output_token_ceiling);
  if (!Number.isSafeInteger(outputCeiling) || outputCeiling < 1) {
    throw new Error("output_token_ceiling must be a positive integer");
  }
  const messages = Array.isArray(command.messages) ? command.messages : [];
  const system = messages.find((item) => item?.role === "system");
  const userMessages = messages.filter((item) => item?.role === "user");
  if (!system || userMessages.length !== 1) {
    throw new Error("subscription request requires one system and one user message");
  }
  const model = runtime.getModel("openai-codex", upstreamModel);
  if (!model) {
    throw new Error(`subscription model unavailable: ${upstreamModel}`);
  }
  const response = await runtime.completeSimple(
    model,
    {
      systemPrompt: String(system.content),
      messages: [
        {
          role: "user",
          content: String(userMessages[0].content),
          timestamp: Date.now(),
        },
      ],
    },
    {
      reasoning: "low",
      timeoutMs: Number(command.timeout_ms),
      maxRetries: 0,
      cacheRetention: "none",
      onPayload(payload) {
        return {
          ...payload,
          text: { ...(payload.text ?? {}), format: decisionFormat },
        };
      },
    },
  );
  if (response.stopReason !== "stop") {
    throw new Error(response.errorMessage || `subscription response stopped with ${response.stopReason}`);
  }
  if (response.usage.output > outputCeiling) {
    throw new Error("subscription response exceeded the application output-token ceiling");
  }
  const inputTokens = response.usage.input + response.usage.cacheRead + response.usage.cacheWrite;
  return {
    id: command.id,
    ok: true,
    provider: response.provider,
    requested_model: requestedModel,
    upstream_model: upstreamModel,
    observed_model: response.responseModel ?? response.model,
    decision_text: textContent(response),
    usage: {
      input_tokens: inputTokens,
      output_tokens: response.usage.output,
      total_tokens: inputTokens + response.usage.output,
      cached_input_tokens: response.usage.cacheRead,
      reasoning_tokens: response.usage.reasoning ?? null,
      subscription_nominal_cost_usd: response.usage.cost.total,
    },
    output_token_ceiling_enforcement: "application_fail_closed",
  };
}

async function handle(command) {
  if (!command || typeof command !== "object") {
    throw new Error("command must be a JSON object");
  }
  if (command.type === "status") {
    return status(command);
  }
  if (command.type === "request") {
    return request(command);
  }
  if (command.type === "close") {
    return { id: command.id, ok: true, closing: true };
  }
  throw new Error(`unsupported command type: ${String(command.type)}`);
}

let buffer = "";
let queue = Promise.resolve();
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  while (true) {
    const newline = buffer.indexOf("\n");
    if (newline < 0) break;
    let line = buffer.slice(0, newline);
    buffer = buffer.slice(newline + 1);
    if (line.endsWith("\r")) line = line.slice(0, -1);
    if (!line) continue;
    queue = queue.then(async () => {
      let command;
      try {
        command = JSON.parse(line);
        const response = await handle(command);
        emit(response);
        if (response.closing) process.exit(0);
      } catch (error) {
        emit({ id: command?.id ?? null, ok: false, error: safeError(error) });
      }
    });
  }
});
process.stdin.on("end", () => {
  queue.finally(() => process.exit(0));
});
