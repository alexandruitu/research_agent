import { describe, expect, it } from "vitest";

import { mergeRef } from "./saveFlow";

const C = "11111111-1111-4111-8111-111111111111";
const P = "22222222-2222-4222-8222-222222222222";

describe("mergeRef", () => {
  it("a first save in My library leads with the personal item", () => {
    expect(mergeRef(null, { id: P, scope: "personal", status: "to_read", collections: [] })).toEqual({
      item_id: P, scope: "personal", status: "to_read", collections: [], company_item_id: null, personal_item_id: P,
    });
  });

  it("the Company item leads once the paper is in both, and the user's own is still named", () => {
    const mine = mergeRef(null, { id: P, scope: "personal", status: "read", collections: [] });
    expect(mergeRef(mine, { id: C, scope: "company", status: "to_read", collections: [] })).toMatchObject({
      item_id: C, scope: "company", status: "to_read", company_item_id: C, personal_item_id: P,
    });
    const company = mergeRef(null, { id: C, scope: "company", status: "relevant", collections: [] });
    expect(mergeRef(company, { id: P, scope: "personal", status: "to_read", collections: [] })).toMatchObject({
      item_id: C, status: "relevant", company_item_id: C, personal_item_id: P,
    });
  });
});
