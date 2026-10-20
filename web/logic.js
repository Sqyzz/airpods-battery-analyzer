(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.AirPodsLogic = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function formatDateLocal(date) {
    return (
      date.getFullYear() +
      "-" +
      pad(date.getMonth() + 1) +
      "-" +
      pad(date.getDate())
    );
  }

  function addDays(date, days) {
    const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    copy.setDate(copy.getDate() + days);
    return copy;
  }

  function buildRangePreset(preset, now) {
    const base = now || new Date();
    const today = new Date(base.getFullYear(), base.getMonth(), base.getDate());

    if (preset === "today") {
      return { start: formatDateLocal(today), end: formatDateLocal(today) };
    }
    if (preset === "7d") {
      return { start: formatDateLocal(addDays(today, -6)), end: formatDateLocal(today) };
    }
    if (preset === "30d") {
      return { start: formatDateLocal(addDays(today, -29)), end: formatDateLocal(today) };
    }
    throw new Error("未知的时间范围预设");
  }

  function buildSeriesData(samples) {
    const l = [];
    const r = [];
    const c = [];
    for (const sample of samples || []) {
      l.push([sample.ts, sample.l == null ? null : sample.l]);
      r.push([sample.ts, sample.r == null ? null : sample.r]);
      c.push([sample.ts, sample.c == null ? null : sample.c]);
    }
    return { l: l, r: r, c: c };
  }

  function formatDuration(minutes) {
    if (minutes == null || !Number.isFinite(Number(minutes))) {
      return "—";
    }
    const total = Math.round(Number(minutes));
    const hours = Math.floor(total / 60);
    const rest = total % 60;
    return hours > 0 ? hours + "h" + pad(rest) + "m" : rest + "m";
  }

  function formatRate(value) {
    if (value == null || !Number.isFinite(Number(value))) {
      return "—";
    }
    return Number(value).toFixed(1) + " %/h";
  }

  function formatFirstDrop(drop) {
    if (!drop) {
      return "—";
    }
    const total = Math.round(Number(drop.seconds) || 0);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    let text =
      hours > 0
        ? hours + "h" + pad(minutes) + "m" + pad(seconds) + "s"
        : minutes + "m" + pad(seconds) + "s";
    if (drop.skipped) {
      text += "（跳→" + drop.to_level + "%）";
    }
    return text;
  }

  function formatBox(start, end) {
    if (start == null && end == null) {
      return "—";
    }
    if (start == null) {
      return end + "%（仅 1 次）";
    }
    if (end == null) {
      return start + "%（仅 1 次）";
    }
    return start === end ? start + "%（无变化）" : start + "%→" + end + "%";
  }

  function formatDelta(start, end) {
    if (start == null || end == null) {
      return "—";
    }
    const delta = start - end;
    const sign = delta >= 0 ? "-" : "+";
    return start + "%→" + end + "%（" + sign + Math.abs(delta) + "）";
  }

  function formatTimeRange(start, end) {
    return String(start).slice(11, 16) + "–" + String(end).slice(11, 16);
  }

  function formatCharge(start, end, rate) {
    if (start == null) {
      return "—";
    }
    if (start >= 100) {
      return "已充满";
    }
    const base = start + "%→" + end + "%";
    if (rate == null || !Number.isFinite(Number(rate))) {
      return base;
    }
    return base + "（" + Number(rate).toFixed(1) + " %/h）";
  }

  function formatCaseCharge(start, end, rate) {
    if (start == null && end == null) {
      return "—";
    }
    if (start == null) {
      return end + "%（仅 1 次）";
    }
    if (end == null) {
      return start + "%（仅 1 次）";
    }
    if (start === end) {
      return start + "%（无变化）";
    }
    const base = start + "%→" + end + "%";
    if (rate == null || !Number.isFinite(Number(rate))) {
      return base;
    }
    const speed = Math.abs(Number(rate)).toFixed(1) + " %/h";
    return base + "（" + speed + (Number(rate) >= 0 ? " 耗电" : " 回充") + "）";
  }

  function buildChargingAreas(intervals, minWidthMs) {
    const width = minWidthMs == null ? 60000 : minWidthMs;
    return (intervals || []).map(function (interval) {
      const end =
        interval.end > interval.start ? interval.end : interval.start + width;
      return [{ xAxis: interval.start }, { xAxis: end }];
    });
  }

  function parseDeepLink(search) {
    const params = new URLSearchParams(search || "");
    const preset = params.get("preset");
    return {
      address: (params.get("address") || "").trim().toUpperCase(),
      preset: ["today", "7d", "30d", "custom"].includes(preset) ? preset : "7d",
      start: params.get("start") || "",
      end: params.get("end") || "",
      autostart: params.get("autostart") === "1",
    };
  }

  return {
    buildRangePreset: buildRangePreset,
    buildSeriesData: buildSeriesData,
    formatDuration: formatDuration,
    formatRate: formatRate,
    formatFirstDrop: formatFirstDrop,
    formatBox: formatBox,
    formatDelta: formatDelta,
    formatTimeRange: formatTimeRange,
    formatCharge: formatCharge,
    formatCaseCharge: formatCaseCharge,
    buildChargingAreas: buildChargingAreas,
    parseDeepLink: parseDeepLink,
  };
});
