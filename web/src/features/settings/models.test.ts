import { describe, expect, it } from "vitest";

import { modelsAvailable } from "../../test/fixtures";
import { modelOptions, providerOf, sharedFamily } from "./models";

describe("model choices", () => {
  it("reads the provider from the id", () => {
    expect(providerOf("anthropic:claude-sonnet-5")).toBe("anthropic");
    expect(providerOf("plain-model")).toBeNull();
    expect(providerOf(null)).toBeNull();
  });

  it("finds one shared family only when two or more reviewers all resolve to the same provider", () => {
    expect(sharedFamily(["anthropic:a", "anthropic:b", "anthropic:c"])).toBe("anthropic");
    expect(sharedFamily(["anthropic:a", "openai:b"])).toBeNull();
    expect(sharedFamily(["anthropic:a", null])).toBeNull();
    expect(sharedFamily(["anthropic:a"])).toBeNull();
  });

  it("offers available models, keeps the current value visible and says why it is not available", () => {
    const options = modelOptions(modelsAvailable().models, "openai:gpt-6");
    expect(options.map((o) => o.label)).toEqual(["anthropic:claude-opus-5-5", "anthropic:claude-sonnet-5", "openai:gpt-6 (key not accepted)"]);
    expect(modelOptions(modelsAvailable().models, "mistral:x").at(-1)).toEqual({ id: "mistral:x", label: "mistral:x (not configured in the worker)", available: false });
    expect(modelOptions(modelsAvailable().models, null).map((o) => o.id)).toEqual(["anthropic:claude-opus-5-5", "anthropic:claude-sonnet-5"]);
  });
});
