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
const { rangeFor, homePath, navigateHome } = await import("../custom_components/glowbright/frontend/glowbright-panel.js");

for (const origin of ["http://ha.local:8123", "https://ha.example.test"]) {
  test(`Home stays on ${origin} and rejects unsafe configured destinations`, () => {
    assert.equal(homePath("/custom-launcher/home?view=1#top", origin), "/custom-launcher/home?view=1#top");
    for (const path of [undefined, "", "home", "https://other.test/home", "//other.test", "/\\other.test", "/%2fother.test", "/%5cother.test", "/a/../home", "/%2e%2e//other.test", "/\n/other.test", "/%09/other.test", "/%", "/%FF"]) {
      assert.equal(homePath(path, origin), "/home-launcher/home", String(path));
    }
  });
  test(`Home uses the native router after internal navigation on ${origin}`, () => {
    const calls=[];
    const targetWindow={location:{origin,pathname:"/glowbright"},history:{pushState(...args){calls.push(args);}},dispatchEvent(event){calls.push(event.type);}};
    for (const route of ["/glowbright", "/glowbright?fuel=gas", "/glowbright/history/2026-10-11"]) {
      targetWindow.location.pathname=route;
      navigateHome("/custom-launcher/home",targetWindow);
    }
    assert.deepEqual(calls, Array.from({length:3},()=>[[null,"","/custom-launcher/home"],"location-changed"]).flat());
    navigateHome("//other.test",targetWindow);
    assert.deepEqual(calls.slice(-2),[[null,"","/home-launcher/home"],"location-changed"]);
  });
}

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
