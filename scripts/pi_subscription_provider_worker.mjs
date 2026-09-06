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

const subscriptionProfiles = Object.freeze({
  "openai-codex": Object.freeze({
    provider: "openai-codex",
    modelAliases: Object.freeze({
      "gpt-5.4-mini": "gpt-5.4-mini",
      "gpt-5.4-2026-03-05": "gpt-5.4",
      "gpt-5.5-2026-04-23": "gpt-5.5",
      "gpt-5.6-sol": "gpt-5.6-sol",
    }),
    outputTokenCeilingEnforcement: "application_fail_closed",
  }),
  "kimi-coding": Object.freeze({
    provider: "kimi-coding",
    modelAliases: Object.freeze({
      "kimi-coding/k3-256k": "k3-256k",
    }),
    outputTokenCeilingEnforcement: "wire_and_application_fail_closed",
  }),
});
const profileName = process.env.LLM_ABM_PI_SUBSCRIPTION_PROFILE ?? "openai-codex";
const subscriptionProfile = subscriptionProfiles[profileName];
if (!subscriptionProfile) {
  throw new Error("unsupported Pi subscription profile");
}
const { provider, modelAliases, outputTokenCeilingEnforcement } = subscriptionProfile;

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

const safeFailureCategories = new Set([
  "request_invalid",
  "authentication",
  "entitlement",
  "quota_exhausted",
  "rate_limited",
  "upstream_unavailable",
  "transport",
  "provider_stop",
  "output_ceiling_exceeded",
]);

const explicitQuotaCodes = new Set([
  "insufficient_quota",
  "insufficient_balance",
  "balance_exhausted",
  "quota_exhausted",
  "subscription_quota_exhausted",
  "usage_limit_reached",
  "credit_balance_too_low",
  "credits_exhausted",
]);

const explicitQuotaCodePattern = new RegExp(`\\b(?:${[...explicitQuotaCodes].join("|")})\\b`, "i");

function normalizedCode(value) {
  return typeof value === "string"
    ? value.trim().toLowerCase().replace(/[\s-]+/g, "_")
    : null;
}

function explicitQuotaFailure(error, message) {
  const codeOrTypeValues = [
    error?.code,
    error?.type,
    error?.category,
    error?.error?.code,
    error?.error?.type,
    error?.response?.data?.error?.code,
    error?.response?.data?.error?.type,
    error?.response?.data?.code,
    error?.response?.data?.type,
    error?.body?.error?.code,
    error?.body?.error?.type,
    error?.body?.code,
    error?.body?.type,
  ];
  if (codeOrTypeValues.some((value) => explicitQuotaCodes.has(normalizedCode(value)))) {
    return true;
  }
  const messages = [
    message,
    error?.error?.message,
    error?.response?.data?.error?.message,
    error?.response?.data?.message,
    error?.body?.error?.message,
    error?.body?.message,
  ]
    .filter((value) => typeof value === "string")
    .join(" ")
    .toLowerCase();
  // Pi may flatten structured SDK failures into an errorMessage string.
  return explicitQuotaCodePattern.test(messages)
    || /insufficient (?:quota|balance|credits)|credit balance (?:is )?too low|(?:quota|balance|credits) (?:has been |is |are )?(?:exhausted|depleted)|(?:(?:weekly|monthly|daily|subscription) )?usage limit (?:has been )?reached|exceeded your current quota,\s*please check your plan and billing details|you(?:'|’)?ve hit your usage limit|余额不足|额度已耗尽/.test(messages);
}

class SafeWorkerFailure extends Error {
  constructor(category, { statusCode = null, waitSeconds = null, waitSource = null } = {}) {
    super("Pi subscription Provider returned a known failure");
    this.name = "SafeWorkerFailure";
    this.category = safeFailureCategories.has(category) ? category : "provider_stop";
    this.status = statusCode;
    this.waitSeconds = this.category === "quota_exhausted" ? null : waitSeconds;
    this.waitSource = this.category === "quota_exhausted" ? null : waitSource;
  }
}

function headerValue(headers, name) {
  if (!headers) return null;
  if (typeof headers.get === "function") return headers.get(name);
  const matched = Object.entries(headers).find(
    ([key]) => typeof key === "string" && key.toLowerCase() === name.toLowerCase(),
  );
  return matched ? matched[1] : null;
}

function classifyFailure(statusCode, name, message, transportFailed) {
  if (statusCode === 400 || statusCode === 422) return "request_invalid";
  if (statusCode === 401) return "authentication";
  if (statusCode === 403 || statusCode === 404) return "entitlement";
  if (statusCode === 408 || statusCode === 409) return "transport";
  if (statusCode === 429) return "rate_limited";
  if (statusCode !== null && statusCode >= 500) return "upstream_unavailable";
  if (statusCode !== null && statusCode >= 400) return "request_invalid";
  const normalized = `${name} ${message}`.toLowerCase();
  if (/authentication|unauthori[sz]ed|invalid auth|invalid token/.test(normalized)) {
    return "authentication";
  }
  if (/permission|forbidden|access denied|not entitled|model unavailable/.test(normalized)) {
    return "entitlement";
  }
  if (/rate.?limit|quota|account limited|too many requests/.test(normalized)) {
    return "rate_limited";
  }
  if (transportFailed || /timeout|timed out|fetch failed|network|connect|socket|aborted/.test(normalized)) {
    return "transport";
  }
  if (/unavailable|overloaded|upstream/.test(normalized)) return "upstream_unavailable";
  return "provider_stop";
}

function safeError(error, observation = {}) {
  const name = typeof error?.name === "string"
    ? error.name
    : error instanceof Error
      ? error.name
      : "Error";
  const message = typeof error?.message === "string"
    ? error.message
    : error instanceof Error
      ? error.message
      : String(error);
  const explicitStatus = Number(error?.status ?? error?.statusCode ?? error?.response?.status);
  const labelledStatus = message.match(
    /\b(?:HTTP(?:\s+status)?|status(?:\s+code)?)[ :=]+(4\d\d|5\d\d)\b/i,
  );
  const leadingStatus = message.match(/^\s*(4\d\d|5\d\d)(?=\s|:|$)/);
  const observedStatus = Number(observation.statusCode);
  const statusCode = Number.isSafeInteger(explicitStatus) && explicitStatus >= 400
    ? explicitStatus
    : Number.isSafeInteger(observedStatus) && observedStatus >= 400
      ? observedStatus
      : labelledStatus
        ? Number(labelledStatus[1])
        : leadingStatus
          ? Number(leadingStatus[1])
          : null;
  const errorHeaders = error?.headers ?? error?.response?.headers;
  const rawHeaderWait = headerValue(errorHeaders, "retry-after")
    ?? error?.waitSeconds
    ?? observation.waitSeconds;
  const headerWait = rawHeaderWait === null || rawHeaderWait === undefined || rawHeaderWait === ""
    ? null
    : Number(rawHeaderWait);
  const waitMatch = message.match(/\bWait\s+([0-9]+(?:\.[0-9]+)?)\s*s\b/i);
  const waitSeconds = headerWait !== null && Number.isFinite(headerWait) && headerWait >= 0
    ? headerWait
    : waitMatch
      ? Number(waitMatch[1])
      : null;
  const waitSource = headerWait !== null && Number.isFinite(headerWait) && headerWait >= 0
    ? error?.waitSource ?? observation.waitSource ?? "retry_after"
    : waitMatch
      ? "provider_wait"
      : null;
  const explicitCategory = safeFailureCategories.has(error?.category) ? error.category : null;
  const category = explicitCategory
    ?? (explicitQuotaFailure(error, message) ? "quota_exhausted" : null)
    ?? classifyFailure(
      statusCode,
      name,
      message,
      observation.transportFailed === true,
    );
  return {
    category,
    status_code: statusCode,
    wait_seconds: category === "quota_exhausted" ? null : waitSeconds,
    wait_source: category === "quota_exhausted" ? null : waitSource,
  };
}

function knownFailure(error, observation = {}) {
  const failure = safeError(error, observation);
  return new SafeWorkerFailure(failure.category, {
    statusCode: failure.status_code,
    waitSeconds: failure.wait_seconds,
    waitSource: failure.wait_source,
  });
}

function observeHttpResponse(observation, status, headers) {
  const normalizedStatus = Number(status);
  if (Number.isSafeInteger(normalizedStatus)) observation.statusCode = normalizedStatus;
  const rawRetryAfter = headerValue(headers, "retry-after");
  const retryAfter = rawRetryAfter === null || rawRetryAfter === undefined || rawRetryAfter === ""
    ? null
    : Number(rawRetryAfter);
  if (retryAfter !== null && Number.isFinite(retryAfter) && retryAfter >= 0) {
    observation.waitSeconds = retryAfter;
    observation.waitSource = "retry_after";
  }
}

function observedFetch(observation) {
  return async (...args) => {
    try {
      const response = await globalThis.fetch(...args);
      observeHttpResponse(observation, response.status, response.headers);
      return response;
    } catch (error) {
      observation.transportFailed = true;
      throw error;
    }
  };
}

function textContent(message) {
  return message.content
    .filter((item) => item.type === "text")
    .map((item) => item.text)
    .join("");
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function providerPayload(payload) {
  if (!isRecord(payload)) {
    throw new SafeWorkerFailure("request_invalid");
  }
  if (provider === "kimi-coding") {
    return {
      ...payload,
      tools: [
        {
          name: decisionFormat.name,
          description: "Return the bounded engagement Decision.",
          input_schema: decisionFormat.schema,
        },
      ],
      tool_choice: { type: "any" },
    };
  }
  return {
    ...payload,
    text: { ...(isRecord(payload.text) ? payload.text : {}), format: decisionFormat },
  };
}

function decisionText(response) {
  if (provider !== "kimi-coding") return textContent(response);
  const toolCalls = response.content.filter((item) => item.type === "toolCall");
  if (response.stopReason !== "toolUse") {
    throw new SafeWorkerFailure("provider_stop");
  }
  if (
    toolCalls.length !== 1
    || toolCalls[0].name !== decisionFormat.name
    || !isRecord(toolCalls[0].arguments)
  ) {
    return "";
  }
  return JSON.stringify(toolCalls[0].arguments);
}

async function status(command) {
  const auth = await runtime.checkAuth(provider);
  const models = Object.values(modelAliases).filter((id) => runtime.getModel(provider, id));
  return {
    id: command.id,
    ok: Boolean(auth) && models.length === Object.keys(modelAliases).length,
    provider,
    auth_type: auth?.type ?? null,
    models,
    requested_model_aliases: modelAliases,
  };
}

async function request(command) {
  const requestedModel = String(command.model ?? "");
  const upstreamModel = modelAliases[requestedModel];
  if (!upstreamModel) {
    throw new SafeWorkerFailure("request_invalid");
  }
  if (command.reasoning_effort !== "low") {
    throw new SafeWorkerFailure("request_invalid");
  }
  const outputCeiling = Number(command.output_token_ceiling);
  if (!Number.isSafeInteger(outputCeiling) || outputCeiling < 1) {
    throw new SafeWorkerFailure("request_invalid");
  }
  const messages = Array.isArray(command.messages) ? command.messages : [];
  const system = messages.find((item) => item?.role === "system");
  const userMessages = messages.filter((item) => item?.role === "user");
  if (!system || userMessages.length !== 1) {
    throw new SafeWorkerFailure("request_invalid");
  }
  const model = runtime.getModel(provider, upstreamModel);
  if (!model) {
    throw new SafeWorkerFailure("entitlement");
  }
  if (provider === "kimi-coding" && model.api !== "anthropic-messages") {
    throw new SafeWorkerFailure("request_invalid");
  }
  const observation = {
    statusCode: null,
    waitSeconds: null,
    waitSource: null,
    transportFailed: false,
  };
  const options = {
    reasoning: "low",
    timeoutMs: Number(command.timeout_ms),
    maxRetries: 0,
    cacheRetention: "none",
    onPayload: providerPayload,
  };
  if (provider === "kimi-coding") {
    options.maxTokens = outputCeiling;
    options.fetch = observedFetch(observation);
    options.onResponse = (response) => {
      observeHttpResponse(observation, response.status, response.headers);
    };
  }
  let response;
  try {
    response = await runtime.completeSimple(
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
      options,
    );
  } catch (error) {
    throw knownFailure(error, observation);
  }
  if (response.stopReason === "length") {
    throw new SafeWorkerFailure("output_ceiling_exceeded");
  }
  if (response.stopReason === "error" || response.stopReason === "aborted") {
    throw knownFailure(
      new Error(response.errorMessage || `subscription response stopped with ${response.stopReason}`),
      observation,
    );
  }
  if (provider !== "kimi-coding" && response.stopReason !== "stop") {
    throw new SafeWorkerFailure("provider_stop");
  }
  if (response.usage.output > outputCeiling) {
    throw new SafeWorkerFailure("output_ceiling_exceeded");
  }
  const inputTokens = response.usage.input + response.usage.cacheRead + response.usage.cacheWrite;
  const nominalCost = response.usage?.cost?.total ?? null;
  const safeNominalCost = typeof nominalCost === "number"
    && Number.isFinite(nominalCost)
    && nominalCost >= 0
    ? nominalCost
    : null;
  return {
    id: command.id,
    ok: true,
    provider: response.provider,
    requested_model: requestedModel,
    upstream_model: upstreamModel,
    observed_model: response.responseModel ?? response.model,
    decision_text: decisionText(response),
    usage: {
      input_tokens: inputTokens,
      output_tokens: response.usage.output,
      total_tokens: inputTokens + response.usage.output,
      cached_input_tokens: response.usage.cacheRead,
      reasoning_tokens: response.usage.reasoning ?? null,
      subscription_nominal_cost_usd: safeNominalCost,
    },
    output_token_ceiling_enforcement: outputTokenCeilingEnforcement,
  };
}

async function handle(command) {
  if (!command || typeof command !== "object") {
    throw new SafeWorkerFailure("request_invalid");
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
  throw new SafeWorkerFailure("request_invalid");
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
