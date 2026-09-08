// Execute the actual bundled calendar functions with Node's built-in test runner.
import assert from "node:assert/strict";
import test from "node:test";

globalThis.HTMLElement = class {};
const registry = new Map();
globalThis.customElements = {
  get(name) { return registry.get(name); },
  define(name, value) {
    if (registry.has(name)) throw new Error("Duplicate element registration");
    registry.set(name, value);
  }
};
const { rangeFor } = await import("../custom_components/glowbright/frontend/glowbright-panel.js");

test("reconnecting with an updated bundle preserves the registered panel", async () => {
  const first = registry.get("glowbright-panel");
  await import("../custom_components/glowbright/frontend/glowbright-panel.js?updated");
  assert.equal(registry.get("glowbright-panel"), first);
});

for (const [date, hours] of [["2026-03-29",23],["2026-10-25",25],["2026-09-07",24]]) {
  test(`London calendar ${date} has ${hours} hours`, () => {
    const range=rangeFor(date,"PT30M");
    assert.equal((Date.parse(range.end)-Date.parse(range.start))/3600000,hours);
  });
}
test("daily view is a Monday week and monthly view is a calendar year",()=>{
  const day=rangeFor("2026-09-09","P1D");
  assert.equal(day.localStart,"2026-09-07");
  assert.equal(day.localEnd,"2026-09-14");
  const month=rangeFor("2026-09-09","P1M");
  assert.equal(month.localStart,"2026-01-01");
  assert.equal(month.localEnd,"2027-01-01");
});
