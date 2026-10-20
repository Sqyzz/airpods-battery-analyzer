const test = require("node:test");
const assert = require("node:assert/strict");
const logic = require("../web/logic.js");

test("buildRangePreset returns local date strings", () => {
  const now = new Date(2026, 9, 20, 15, 30, 0);

  assert.deepEqual(logic.buildRangePreset("today", now), {
    start: "2026-10-20",
    end: "2026-10-20",
  });
  assert.deepEqual(logic.buildRangePreset("7d", now), {
    start: "2026-10-14",
    end: "2026-10-20",
  });
  assert.deepEqual(logic.buildRangePreset("30d", now), {
    start: "2026-09-21",
    end: "2026-10-20",
  });
});

test("buildRangePreset rejects unknown presets", () => {
  assert.throws(() => logic.buildRangePreset("nope", new Date()), /未知/);
});

test("buildSeriesData keeps gaps as null", () => {
  const series = logic.buildSeriesData([
    { ts: 1000, l: 100, r: 99, c: null },
    { ts: 2000, l: 98, r: null, c: 65 },
  ]);

  assert.deepEqual(series.l, [[1000, 100], [2000, 98]]);
  assert.deepEqual(series.r, [[1000, 99], [2000, null]]);
  assert.deepEqual(series.c, [[1000, null], [2000, 65]]);
});

test("buildSeriesData handles an empty list", () => {
  assert.deepEqual(logic.buildSeriesData([]), { l: [], r: [], c: [] });
});

test("formatDuration uses hours and minutes", () => {
  assert.equal(logic.formatDuration(217), "3h37m");
  assert.equal(logic.formatDuration(63), "1h03m");
  assert.equal(logic.formatDuration(10), "10m");
  assert.equal(logic.formatDuration(0), "0m");
  assert.equal(logic.formatDuration(null), "—");
});

test("formatRate handles missing values", () => {
  assert.equal(logic.formatRate(11.94), "11.9 %/h");
  assert.equal(logic.formatRate(null), "—");
});

test("formatFirstDrop renders durations and skipped broadcasts", () => {
  assert.equal(
    logic.formatFirstDrop({ seconds: 298, to_level: 99, skipped: false }),
    "4m58s"
  );
  assert.equal(
    logic.formatFirstDrop({ seconds: 780, to_level: 96, skipped: true }),
    "13m00s（跳→96%）"
  );
  assert.equal(logic.formatFirstDrop(null), "—");
});

test("formatBox renders start and end readings", () => {
  assert.equal(logic.formatBox(63, 52), "63%→52%");
  assert.equal(logic.formatBox(65, 65), "65%（无变化）");
  assert.equal(logic.formatBox(null, 53), "53%（仅 1 次）");
  assert.equal(logic.formatBox(null, null), "—");
});

test("formatDelta renders signed drops", () => {
  assert.equal(logic.formatDelta(100, 57), "100%→57%（-43）");
  assert.equal(logic.formatDelta(68, 69), "68%→69%（+1）");
  assert.equal(logic.formatDelta(null, 57), "—");
});

test("formatTimeRange uses HH:MM from the API timestamps", () => {
  assert.equal(
    logic.formatTimeRange("2026-10-19 13:59:11", "2026-10-19 15:34:44"),
    "13:59–15:34"
  );
});

test("parseDeepLink extracts address, preset, dates and autostart", () => {
  const link = logic.parseDeepLink(
    "?address=cc:4b:04:2c:fe:08&preset=custom&start=2026-10-19&end=2026-10-20&autostart=1"
  );

  assert.deepEqual(link, {
    address: "CC:4B:04:2C:FE:08",
    preset: "custom",
    start: "2026-10-19",
    end: "2026-10-20",
    autostart: true,
  });
});

test("parseDeepLink falls back to sensible defaults", () => {
  assert.deepEqual(logic.parseDeepLink(""), {
    address: "",
    preset: "7d",
    start: "",
    end: "",
    autostart: false,
  });
  assert.equal(logic.parseDeepLink("?preset=bogus").preset, "7d");
});

test("formatCharge renders charge levels and rates", () => {
  assert.equal(logic.formatCharge(20, 100, 68.57, 70), "20%→100%（68.6 %/h）");
  assert.equal(logic.formatCharge(50, 80, 60, null), "50%→80%（60.0 %/h）");
  assert.equal(logic.formatCharge(100, 100, 0, 0), "已充满");
  assert.equal(logic.formatCharge(null, null, null, null), "—");
});

test("formatCaseCharge distinguishes drain and recharge", () => {
  assert.equal(
    logic.formatCaseCharge(90, 78, 10.29),
    "90%→78%（10.3 %/h 耗电）"
  );
  assert.equal(
    logic.formatCaseCharge(50, 60, -20),
    "50%→60%（20.0 %/h 回充）"
  );
  assert.equal(logic.formatCaseCharge(65, 65, 0), "65%（无变化）");
  assert.equal(logic.formatCaseCharge(53, null, null), "53%（仅 1 次）");
  assert.equal(logic.formatCaseCharge(null, null, null), "—");
});

test("buildChargingAreas gives zero-width intervals a visible minimum", () => {
  const areas = logic.buildChargingAreas([
    { start: 1000, end: 5000 },
    { start: 10000, end: 10000 },
  ]);

  assert.deepEqual(areas, [
    [{ xAxis: 1000 }, { xAxis: 5000 }],
    [{ xAxis: 10000 }, { xAxis: 70000 }],
  ]);
});
