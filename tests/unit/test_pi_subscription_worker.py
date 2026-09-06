from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import llm_abm_sim.providers.pi_subscription as pi_subscription_module
from llm_abm_sim.providers.pi_subscription import (
    PiKimiSubscriptionProviderClient,
    PiSubscriptionProviderError,
)


def _fake_pi_package(root: Path) -> Path:
    package_root = root / "pi-coding-agent"
    dist = package_root / "dist"
    (dist / "bundle").mkdir(parents=True)
    (dist / "core").mkdir(parents=True)
    (package_root / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    (dist / "bundle" / "cli.js").write_text("", encoding="utf-8")
    (dist / "core" / "http-dispatcher.js").write_text(
        """
export function applyHttpProxySettings() {}
export function configureHttpDispatcher() {}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (dist / "index.js").write_text(
        """
const decision = {
  engage: true,
  probability: 0.8,
  reason: "fit",
  confidence: 0.9,
  action: "like",
};
if (["observed_rate_limited", "explicit_quota_429"].includes(process.env.FAKE_KIMI_SCENARIO)) {
  globalThis.fetch = async () => new Response("", {
    status: 429,
    headers: { "retry-after": "17" },
  });
}

export class SettingsManager {
  static create() {
    return {
      getGlobalSettings() { return {}; },
      getHttpIdleTimeoutMs() { return 1000; },
    };
  }
}

export class ModelRuntime {
  static async create() { return new ModelRuntime(); }
  async checkAuth() { return { type: "oauth" }; }
  getModel(provider, id) {
    if (provider !== "kimi-coding" || id !== "k3-256k") return undefined;
    return {
      id,
      provider,
      api: "anthropic-messages",
      reasoning: true,
      maxTokens: 131072,
    };
  }
  async completeSimple(model, context, options) {
    const scenario = process.env.FAKE_KIMI_SCENARIO ?? "success";
    const failures = {
      request_invalid: "400 invalid request",
      authentication: "401 invalid authentication",
      entitlement: "403 model access denied",
      rate_limited: "429 account limited; Wait 13s before retry",
      upstream_unavailable: "503 upstream unavailable",
      upstream_502: "502 upstream unavailable",
      transport: "fetch failed while connecting to upstream",
      generic_quota_429: "429 quota",
      resource_exhausted_429: "429 RESOURCE_EXHAUSTED",
      explicit_phrase_403: "403 credit balance is too low",
      flattened_quota_code: '429 {"error":{"type":"usage_limit_reached"}}',
    };
    if (scenario === "explicit_code_429") {
      const error = new Error("429 ordinary rate limit");
      error.code = "insufficient_quota";
      throw error;
    }
    if (scenario === "explicit_type_403") {
      const error = new Error("403 access denied");
      error.type = "insufficient_balance";
      throw error;
    }
    if (scenario === "explicit_body_429") {
      const error = new Error("429 ordinary rate limit");
      error.body = {error: {type: "subscription_quota_exhausted"}};
      throw error;
    }
    if (scenario === "ambiguous_quota_503") {
      throw new Error("503 exceeded your current quota");
    }
    if (scenario === "explicit_billing_429") {
      throw new Error("429 You exceeded your current quota, please check your plan and billing details.");
    }
    if (scenario === "explicit_quota_429") {
      await options.fetch("https://offline-observation.example.test");
      return {
        role: "assistant",
        content: [],
        api: "anthropic-messages",
        provider: "kimi-coding",
        model: model.id,
        usage: {
          input: 0,
          output: 0,
          cacheRead: 0,
          cacheWrite: 0,
          totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
        },
        stopReason: "error",
        errorMessage: "quota has been exhausted",
        timestamp: Date.now(),
      };
    }
    if (scenario in failures) {
      return {
        role: "assistant",
        content: [],
        api: "anthropic-messages",
        provider: "kimi-coding",
        model: model.id,
        usage: {
          input: 0,
          output: 0,
          cacheRead: 0,
          cacheWrite: 0,
          totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
        },
        stopReason: "error",
        errorMessage: failures[scenario],
        timestamp: Date.now(),
      };
    }
    if (scenario === "length") {
      return {
        role: "assistant",
        content: [],
        api: "anthropic-messages",
        provider: "kimi-coding",
        model: model.id,
        usage: {
          input: 20,
          output: 256,
          cacheRead: 0,
          cacheWrite: 0,
          totalTokens: 276,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
        },
        stopReason: "length",
        timestamp: Date.now(),
      };
    }
    if (options.reasoning !== "low" || options.maxTokens !== 256 || options.maxRetries !== 0) {
      throw new Error("400 worker options do not enforce the frozen Kimi contract");
    }
    if (typeof options.fetch !== "function") {
      throw new Error("400 worker does not provide safe HTTP observation");
    }
    if (scenario === "observed_rate_limited") {
      await options.fetch("https://offline-observation.example.test");
      return {
        role: "assistant",
        content: [],
        api: "anthropic-messages",
        provider: "kimi-coding",
        model: model.id,
        usage: {
          input: 0,
          output: 0,
          cacheRead: 0,
          cacheWrite: 0,
          totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
        },
        stopReason: "error",
        errorMessage: "request failed",
        timestamp: Date.now(),
      };
    }
    const payload = await options.onPayload(
      {
        model: model.id,
        messages: [{ role: "user", content: "test" }],
        max_tokens: options.maxTokens ?? model.maxTokens,
      },
      model,
    );
    const tool = payload.tools?.[0];
    if (
      payload.text !== undefined
      || payload.max_tokens !== 256
      || payload.tool_choice?.type !== "any"
      || payload.tools?.length !== 1
      || tool?.name !== "engage_decision"
      || tool?.input_schema?.additionalProperties !== false
      || tool?.input_schema?.required?.length !== 5
    ) {
      throw new Error("400 worker payload is not the frozen Anthropic tool contract");
    }
    return {
      role: "assistant",
      content: [
        {
          type: "toolCall",
          id: "tool_test",
          name: "engage_decision",
          arguments: decision,
        },
      ],
      api: "anthropic-messages",
      provider: "kimi-coding",
      model: model.id,
      responseModel: model.id,
      usage: {
        input: 20,
        output: 10,
        cacheRead: 0,
        cacheWrite: 0,
        reasoning: 2,
        totalTokens: 30,
        ...(scenario === "missing_cost"
          ? {}
          : { cost: scenario === "invalid_cost"
            ? { total: "not-a-number" }
            : { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }),
      },
      stopReason: "toolUse",
      timestamp: Date.now(),
    };
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return dist / "bundle" / "cli.js"


def _use_fake_pi_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    scenario: str = "success",
) -> None:
    node = shutil.which("node")
    assert node is not None
    pi_cli = _fake_pi_package(tmp_path)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    monkeypatch.setenv("FAKE_KIMI_SCENARIO", scenario)
    monkeypatch.setattr(
        pi_subscription_module.shutil,
        "which",
        lambda executable: str(pi_cli) if executable == "pi" else node,
    )


def _messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "Return the frozen Decision contract."},
        {"role": "user", "content": "Evaluate this message."},
    ]


def test_real_worker_uses_kimi_anthropic_tool_contract_and_wire_token_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_fake_pi_runtime(tmp_path, monkeypatch)

    with PiKimiSubscriptionProviderClient(response_timeout_seconds=5.0) as client:
        response = client.create_response(
            _messages(),
            "kimi-coding/k3-256k",
            reasoning_effort="low",
            output_token_ceiling=256,
        )

    assert response.decision_text == (
        '{"engage":true,"probability":0.8,"reason":"fit",'
        '"confidence":0.9,"action":"like"}'
    )
    assert response.observed_model == "k3-256k"
    assert response.usage_status == "complete"
    assert response.output_tokens == 10
    assert client.output_token_ceiling_enforcement == "wire_and_application_fail_closed"


@pytest.mark.parametrize(
    ("scenario", "category", "status_code", "retryable", "wait_seconds", "wait_source"),
    [
        ("request_invalid", "request_invalid", 400, False, None, None),
        ("authentication", "authentication", 401, False, None, None),
        ("entitlement", "entitlement", 403, False, None, None),
        ("rate_limited", "rate_limited", 429, True, 13.0, "provider_wait"),
        ("generic_quota_429", "rate_limited", 429, True, None, None),
        ("resource_exhausted_429", "rate_limited", 429, True, None, None),
        (
            "observed_rate_limited",
            "rate_limited",
            429,
            True,
            17.0,
            "retry_after",
        ),
        ("explicit_quota_429", "quota_exhausted", 429, False, None, None),
        ("explicit_code_429", "quota_exhausted", 429, False, None, None),
        ("flattened_quota_code", "quota_exhausted", 429, False, None, None),
        ("explicit_type_403", "quota_exhausted", 403, False, None, None),
        ("explicit_body_429", "quota_exhausted", 429, False, None, None),
        ("explicit_phrase_403", "quota_exhausted", 403, False, None, None),
        ("ambiguous_quota_503", "upstream_unavailable", 503, True, None, None),
        ("explicit_billing_429", "quota_exhausted", 429, False, None, None),
        ("upstream_unavailable", "upstream_unavailable", 503, True, None, None),
        ("upstream_502", "upstream_unavailable", 502, True, None, None),
        ("transport", "transport", None, True, None, None),
        ("length", "output_ceiling_exceeded", None, False, None, None),
    ],
)
def test_real_worker_preserves_allowlisted_kimi_failure_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    category: str,
    status_code: int | None,
    retryable: bool,
    wait_seconds: float | None,
    wait_source: str | None,
) -> None:
    _use_fake_pi_runtime(tmp_path, monkeypatch, scenario=scenario)

    with PiKimiSubscriptionProviderClient(response_timeout_seconds=5.0) as client:
        with pytest.raises(PiSubscriptionProviderError) as captured:
            client.create_response(
                _messages(),
                "kimi-coding/k3-256k",
                reasoning_effort="low",
                output_token_ceiling=256,
            )

    assert captured.value.category == category
    assert captured.value.status_code == status_code
    assert captured.value.retryable is retryable
    assert captured.value.wait_seconds == wait_seconds
    assert captured.value.wait_source == wait_source
    assert captured.value.lane_cooldown is (
        category in {"rate_limited", "upstream_unavailable"}
    )
    assert scenario not in str(captured.value)


@pytest.mark.parametrize("scenario", ["missing_cost", "invalid_cost"])
def test_real_worker_returns_null_for_optional_or_invalid_nominal_cost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    _use_fake_pi_runtime(tmp_path, monkeypatch, scenario=scenario)

    with PiKimiSubscriptionProviderClient(response_timeout_seconds=5.0) as client:
        response = client.create_response(
            _messages(),
            "kimi-coding/k3-256k",
            reasoning_effort="low",
            output_token_ceiling=256,
        )

    assert response.usage_status == "complete"
    assert client.last_subscription_nominal_cost_usd is None
    assert client.subscription_nominal_cost_usd_total is None
