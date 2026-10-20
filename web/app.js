(function () {
  "use strict";

  const logic = window.AirPodsLogic;
  const ADDRESS_RE = /^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$/;

  const state = {
    devices: [],
    preset: "7d",
    jobId: null,
    pollTimer: null,
    chart: null,
    analysis: null,
    current: null,
  };

  const els = {};

  function bindElements() {
    els.deviceSelect = document.getElementById("deviceSelect");
    els.scanDays = document.getElementById("scanDays");
    els.scanBtn = document.getElementById("scanBtn");
    els.manualAddress = document.getElementById("manualAddress");
    els.rangeButtons = document.getElementById("rangeButtons");
    els.customRange = document.getElementById("customRange");
    els.customStart = document.getElementById("customStart");
    els.customEnd = document.getElementById("customEnd");
    els.analyzeBtn = document.getElementById("analyzeBtn");
    els.cancelBtn = document.getElementById("cancelBtn");
    els.status = document.getElementById("status");
    els.summary = document.getElementById("summary");
    els.statSessions = document.getElementById("statSessions");
    els.statDuration = document.getElementById("statDuration");
    els.statDropL = document.getElementById("statDropL");
    els.statRateL = document.getElementById("statRateL");
    els.statDropR = document.getElementById("statDropR");
    els.statRateR = document.getElementById("statRateR");
    els.statSamples = document.getElementById("statSamples");
    els.statCharging = document.getElementById("statCharging");
    els.statCaseDrain = document.getElementById("statCaseDrain");
    els.chartPanel = document.getElementById("chartPanel");
    els.chart = document.getElementById("chart");
    els.chartMeta = document.getElementById("chartMeta");
    els.resetZoomBtn = document.getElementById("resetZoomBtn");
    els.tablePanel = document.getElementById("tablePanel");
    els.sessionsBody = document.getElementById("sessionsBody");
    els.coverageNote = document.getElementById("coverageNote");
    els.chargingPanel = document.getElementById("chargingPanel");
    els.chargingBody = document.getElementById("chargingBody");
  }

  async function api(path, options) {
    const response = await fetch(path, options);
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }
    if (!response.ok) {
      throw new Error(
        (payload && payload.error) || "请求失败（HTTP " + response.status + "）"
      );
    }
    return payload;
  }

  function setStatus(text, kind, spinner) {
    els.status.className = "status " + (kind || "info");
    els.status.textContent = "";
    if (!text) {
      els.status.classList.add("hidden");
      return;
    }
    if (spinner) {
      const dot = document.createElement("span");
      dot.className = "spinner";
      els.status.appendChild(dot);
    }
    els.status.appendChild(document.createTextNode(text));
  }

  function setBusy(busy) {
    els.analyzeBtn.disabled = busy;
    els.cancelBtn.classList.toggle("hidden", !busy);
  }

  function formatInt(value) {
    return Number(value || 0).toLocaleString("zh-CN");
  }

  function setCustomDefaults() {
    const today = logic.buildRangePreset("today");
    els.customStart.value = today.start;
    els.customEnd.value = today.end;
  }

  function applyPreset(preset) {
    state.preset = preset;
    Array.prototype.forEach.call(
      els.rangeButtons.querySelectorAll(".range-btn"),
      function (button) {
        button.classList.toggle("active", button.dataset.range === preset);
      }
    );
    els.customRange.classList.toggle("hidden", preset !== "custom");
  }

  function renderDeviceOptions() {
    const previous = els.deviceSelect.value;
    els.deviceSelect.textContent = "";

    if (!state.devices.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "未发现设备，可手动输入地址";
      els.deviceSelect.appendChild(option);
      return;
    }

    for (const device of state.devices) {
      const option = document.createElement("option");
      option.value = device.address;
      const name = device.name || "未命名设备";
      option.textContent = name + " · " + device.address;
      els.deviceSelect.appendChild(option);
    }

    if (state.devices.some((device) => device.address === previous)) {
      els.deviceSelect.value = previous;
    }
  }

  async function loadDevices(scanDays) {
    const path = scanDays
      ? "/api/devices?scan=" + encodeURIComponent(scanDays)
      : "/api/devices";

    if (scanDays) {
      setStatus("正在扫描最近 " + scanDays + " 天的蓝牙电量广播…", "info", true);
    } else {
      setStatus("正在读取设备列表…", "info", true);
    }

    try {
      const data = await api(path);
      state.devices = (data && data.devices) || [];
      renderDeviceOptions();

      if (!state.devices.length) {
        setStatus(
          "还没有发现广播过电量的设备。可以手动输入蓝牙地址，或扩大扫描范围。",
          "warn",
          false
        );
      } else if (scanDays) {
        setStatus("扫描完成，发现 " + state.devices.length + " 个设备。", "success", false);
      } else {
        setStatus("", "info", false);
      }
    } catch (error) {
      setStatus("设备扫描失败：" + error.message, "error", false);
    }
  }

  function getAddress() {
    const manual = els.manualAddress.value.trim();
    if (manual) {
      if (!ADDRESS_RE.test(manual)) {
        throw new Error("蓝牙地址格式无效，应为 XX:XX:XX:XX:XX:XX");
      }
      return manual.toUpperCase();
    }
    const selected = els.deviceSelect.value;
    if (!selected) {
      throw new Error("请选择一个设备，或手动输入蓝牙地址");
    }
    return selected;
  }

  function getRange() {
    if (state.preset === "custom") {
      const start = els.customStart.value;
      const end = els.customEnd.value;
      if (!start || !end) {
        throw new Error("请选择自定义的开始和结束日期");
      }
      if (end < start) {
        throw new Error("结束日期不能早于开始日期");
      }
      return { start: start, end: end };
    }
    return logic.buildRangePreset(state.preset);
  }

  async function analyze() {
    if (state.jobId) {
      return;
    }

    let address;
    let range;
    try {
      address = getAddress();
      range = getRange();
    } catch (error) {
      setStatus(error.message, "error", false);
      return;
    }

    state.current = { address: address, range: range };
    setBusy(true);
    setStatus("正在准备日志查询…", "info", true);

    try {
      const job = await api("/api/fetch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          address: address,
          start: range.start,
          end: range.end,
        }),
      });
      state.jobId = job.id;
      handleJob(job);
    } catch (error) {
      state.jobId = null;
      setBusy(false);
      setStatus("查询失败：" + error.message, "error", false);
    }
  }

  function handleJob(job) {
    if (job.status === "queued" || job.status === "running") {
      const stage = job.stage || "正在读取统一日志";
      setStatus(
        stage +
          " · 已读 " +
          formatInt(job.lines) +
          " 行 · " +
          formatInt(job.samples) +
          " 条样本 · " +
          Math.round(job.elapsed_seconds) +
          "s",
        "info",
        true
      );
      schedulePoll();
      return;
    }

    if (job.status === "done") {
      setStatus("日志读取完成，正在分析…", "info", true);
      finishAnalysis();
      return;
    }

    state.jobId = null;
    setBusy(false);

    if (job.status === "cancelled") {
      setStatus("已取消本次抓取。", "warn", false);
    } else {
      setStatus("抓取失败：" + (job.error || "未知错误"), "error", false);
    }
  }

  function schedulePoll() {
    clearTimeout(state.pollTimer);
    state.pollTimer = setTimeout(async function () {
      if (!state.jobId) {
        return;
      }
      try {
        const job = await api("/api/jobs/" + state.jobId);
        handleJob(job);
      } catch (error) {
        state.jobId = null;
        setBusy(false);
        setStatus("获取进度失败：" + error.message, "error", false);
      }
    }, 800);
  }

  async function finishAnalysis() {
    const address = state.current.address;
    const range = state.current.range;

    try {
      const query = new URLSearchParams({
        address: address,
        start: range.start,
        end: range.end,
        gap: "60",
      });
      const data = await api("/api/analysis?" + query.toString());
      state.jobId = null;
      setBusy(false);
      render(data);

      if (!data.samples.length) {
        setStatus(
          "所选范围内没有可用的电量广播。日志可能已轮转，或设备在此期间未连接。",
          "warn",
          false
        );
      } else if (!data.sessions.length && data.stats.connected_sample_count === 0) {
        setStatus(
          "有 " +
            formatInt(data.stats.sample_count) +
            " 条电量广播，但所选时段内该设备没有与这台 Mac 保持连接，无法切分使用会话。",
          "warn",
          false
        );
      } else {
        setStatus(
          "分析完成：" +
            data.sessions.length +
            " 段使用会话，" +
            formatInt(data.stats.sample_count) +
            " 条样本。",
          "success",
          false
        );
      }
    } catch (error) {
      state.jobId = null;
      setBusy(false);
      setStatus("分析失败：" + error.message, "error", false);
    }
  }

  async function cancelFetch() {
    if (!state.jobId) {
      return;
    }
    setStatus("正在取消…", "info", true);
    try {
      await api("/api/jobs/" + state.jobId + "/cancel", { method: "POST" });
    } catch (error) {
      setStatus("取消失败：" + error.message, "error", false);
    }
  }

  function render(data) {
    state.analysis = data;
    els.summary.classList.remove("hidden");
    renderSummary(data.stats);

    const chart = data.chart || {};
    if (chart.applied) {
      els.chartMeta.textContent =
        "曲线已降采样：" +
        formatInt(chart.original_points) +
        " → " +
        formatInt(chart.returned_points) +
        " 点";
    } else if (chart.returned_points != null) {
      els.chartMeta.textContent =
        "曲线为原始精度（" + formatInt(chart.returned_points) + " 点）";
    } else {
      els.chartMeta.textContent = "";
    }

    if (data.samples.length) {
      els.chartPanel.classList.remove("hidden");
      renderChart(data);
    } else {
      els.chartPanel.classList.add("hidden");
    }

    els.tablePanel.classList.remove("hidden");
    renderSessions(data.sessions, data.samples.length > 0);
    renderCoverage(data.coverage);

    els.chargingPanel.classList.remove("hidden");
    renderChargingSessions(data.charging_sessions || []);
  }

  function renderSummary(stats) {
    els.statSessions.textContent = stats.session_count + " 段";
    els.statDuration.textContent = logic.formatDuration(stats.total_minutes);
    els.statDropL.textContent = "-" + stats.total_l_drop + "%";
    els.statRateL.textContent = "平均 " + logic.formatRate(stats.avg_rate_l);
    els.statDropR.textContent = "-" + stats.total_r_drop + "%";
    els.statRateR.textContent = "平均 " + logic.formatRate(stats.avg_rate_r);
    els.statSamples.textContent = formatInt(stats.sample_count);

    const chargingCount = stats.charging_session_count || 0;
    const caseDrain = stats.total_case_drain || 0;
    els.statCharging.textContent = chargingCount + " 段";
    if (caseDrain > 0) {
      els.statCaseDrain.textContent = "充电盒累计耗电 " + caseDrain + "%";
    } else if (caseDrain < 0) {
      els.statCaseDrain.textContent = "充电盒累计回充 " + Math.abs(caseDrain) + "%";
    } else {
      els.statCaseDrain.textContent = "充电盒无明显变化";
    }
  }

  function tooltipFormatter(params) {
    if (!params || !params.length) {
      return "";
    }
    const date = new Date(params[0].value[0]);
    const pad = function (value) {
      return String(value).padStart(2, "0");
    };
    const time =
      date.getFullYear() +
      "-" +
      pad(date.getMonth() + 1) +
      "-" +
      pad(date.getDate()) +
      " " +
      pad(date.getHours()) +
      ":" +
      pad(date.getMinutes()) +
      ":" +
      pad(date.getSeconds());

    const rows = params
      .filter(function (item) {
        return item.value && item.value[1] != null;
      })
      .map(function (item) {
        return (
          '<div style="display:flex;justify-content:space-between;gap:18px">' +
          "<span>" +
          item.marker +
          item.seriesName +
          "</span><b>" +
          item.value[1] +
          "%</b></div>"
        );
      });

    return (
      '<div style="font-weight:600;margin-bottom:4px">' + time + "</div>" + rows.join("")
    );
  }

  function renderChart(data) {
    if (!state.chart) {
      state.chart = window.echarts.init(els.chart);
      window.addEventListener("resize", function () {
        if (state.chart) {
          state.chart.resize();
        }
      });
    }

    const seriesData = logic.buildSeriesData(data.samples);
    const chargingAreas = logic.buildChargingAreas(data.charging_intervals);

    state.chart.setOption(
      {
        animation: false,
        color: ["#2563eb", "#dc2626", "#059669"],
        tooltip: {
          trigger: "axis",
          confine: true,
          formatter: tooltipFormatter,
        },
        legend: {
          top: 0,
          itemWidth: 14,
          itemHeight: 8,
          data: ["左耳", "右耳", "充电盒"],
        },
        grid: { left: 48, right: 24, top: 42, bottom: 78 },
        xAxis: {
          type: "time",
          boundaryGap: false,
          axisLine: { lineStyle: { color: "#cbd5e1" } },
          axisLabel: { color: "#64748b", hideOverlap: true },
        },
        yAxis: {
          type: "value",
          min: 0,
          max: 100,
          interval: 20,
          axisLabel: { formatter: "{value}%", color: "#64748b" },
          splitLine: { lineStyle: { color: "#eef2f7" } },
        },
        dataZoom: [
          { type: "inside", filterMode: "none" },
          {
            type: "slider",
            height: 18,
            bottom: 16,
            filterMode: "none",
            borderColor: "#e2e8f0",
          },
        ],
        series: [
          {
            name: "左耳",
            type: "line",
            showSymbol: false,
            connectNulls: false,
            sampling: "lttb",
            lineStyle: { width: 2 },
            emphasis: { focus: "series" },
            data: seriesData.l,
            markArea: {
              silent: true,
              itemStyle: { color: "rgba(245, 158, 11, 0.16)" },
              data: chargingAreas,
            },
          },
          {
            name: "右耳",
            type: "line",
            showSymbol: false,
            connectNulls: false,
            sampling: "lttb",
            lineStyle: { width: 2 },
            emphasis: { focus: "series" },
            data: seriesData.r,
          },
          {
            name: "充电盒",
            type: "line",
            showSymbol: false,
            connectNulls: false,
            sampling: "lttb",
            lineStyle: { width: 2, type: "dashed" },
            emphasis: { focus: "series" },
            data: seriesData.c,
          },
        ],
      },
      true
    );

    state.chart.resize();
  }

  function zoomToSession(session) {
    if (!state.chart) {
      return;
    }
    state.chart.dispatchAction({
      type: "dataZoom",
      dataIndex: 0,
      startValue: session.start_ms,
      endValue: session.end_ms,
    });
    state.chart.dispatchAction({
      type: "dataZoom",
      dataIndex: 1,
      startValue: session.start_ms,
      endValue: session.end_ms,
    });
  }

  function renderSessions(sessions, hasSamples) {
    els.sessionsBody.textContent = "";

    if (!sessions.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 9;
      cell.className = "empty";
      cell.textContent = hasSamples
        ? "没有检测到连续的非充电使用会话，试试扩大时间范围。"
        : "所选范围内没有可用的电量广播。";
      row.appendChild(cell);
      els.sessionsBody.appendChild(row);
      return;
    }

    sessions.forEach(function (session) {
      const row = document.createElement("tr");
      const values = [
        session.start.slice(0, 10),
        logic.formatTimeRange(session.start, session.end),
        logic.formatDuration(session.duration_min),
        logic.formatDelta(session.l_start, session.l_end),
        logic.formatDelta(session.r_start, session.r_end),
        logic.formatRate(session.l_rate) + " / " + logic.formatRate(session.r_rate),
        logic.formatFirstDrop(session.l_first_drop) +
          " / " +
          logic.formatFirstDrop(session.r_first_drop),
        logic.formatBox(session.c_start, session.c_end),
        String(session.sample_count),
      ];

      values.forEach(function (value) {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.appendChild(cell);
      });

      if (session.max_gap_min != null && session.max_gap_min > 5) {
        row.children[2].textContent += " ⚠";
        row.children[2].title = "最大采样间隔 " + session.max_gap_min + " 分钟";
      }
      row.children[6].title =
        "左耳 " +
        (session.l_first_drop ? session.l_first_drop.seconds + " 秒" : "无法计量") +
        "，右耳 " +
        (session.r_first_drop ? session.r_first_drop.seconds + " 秒" : "无法计量");
      row.title = session.start + " → " + session.end;

      row.addEventListener("click", function () {
        clearSelection();
        row.classList.add("selected");
        zoomToSession(session);
      });

      els.sessionsBody.appendChild(row);
    });
  }

  function clearSelection() {
    [els.sessionsBody, els.chargingBody].forEach(function (body) {
      if (!body) {
        return;
      }
      Array.prototype.forEach.call(body.querySelectorAll("tr"), function (row) {
        row.classList.remove("selected");
      });
    });
  }

  function renderChargingSessions(sessions) {
    els.chargingBody.textContent = "";

    if (!sessions.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 8;
      cell.className = "empty";
      cell.textContent = "所选范围内没有检测到充电会话。";
      row.appendChild(cell);
      els.chargingBody.appendChild(row);
      return;
    }

    sessions.forEach(function (session) {
      const row = document.createElement("tr");
      let fullText = "—";
      if (session.full) {
        fullText =
          session.full_min && session.full_min > 0
            ? logic.formatDuration(session.full_min)
            : "已充满";
      }

      const values = [
        session.start.slice(0, 10),
        logic.formatTimeRange(session.start, session.end),
        logic.formatDuration(session.duration_min),
        logic.formatCharge(session.l_start, session.l_end, session.l_rate),
        logic.formatCharge(session.r_start, session.r_end, session.r_rate),
        logic.formatCaseCharge(session.c_start, session.c_end, session.c_rate),
        fullText,
        String(session.sample_count),
      ];

      values.forEach(function (value) {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.appendChild(cell);
      });

      row.title = session.start + " → " + session.end;
      row.addEventListener("click", function () {
        clearSelection();
        row.classList.add("selected");
        zoomToSession(session);
      });

      els.chargingBody.appendChild(row);
    });
  }

  function renderCoverage(coverage) {
    const parts = [];

    if (!coverage.sample_count) {
      parts.push(
        "请求范围：" +
          coverage.requested.start +
          " → " +
          coverage.requested.end +
          "，未找到电量广播。"
      );
    } else {
      parts.push(
        "实际数据：" +
          coverage.first_sample +
          " → " +
          coverage.last_sample +
          "，共 " +
          formatInt(coverage.sample_count) +
          " 条样本。"
      );

      const requestedStart = coverage.requested.start.slice(0, 10);
      const firstDay = coverage.first_sample.slice(0, 10);
      if (firstDay > requestedStart) {
        parts.push("更早的日志已被系统轮转，实际只能从 " + firstDay + " 开始。");
      }
    }

    if (coverage.missing && coverage.missing.length) {
      parts.push(
        "仍有 " + coverage.missing.length + " 段缓存缺口，可再次点击分析补抓。"
      );
    }

    els.coverageNote.textContent = parts.join(" ");
  }

  function resetZoom() {
    if (!state.chart) {
      return;
    }
    state.chart.dispatchAction({ type: "dataZoom", dataIndex: 0, start: 0, end: 100 });
    state.chart.dispatchAction({ type: "dataZoom", dataIndex: 1, start: 0, end: 100 });
  }

  function setupEvents() {
    Array.prototype.forEach.call(
      els.rangeButtons.querySelectorAll(".range-btn"),
      function (button) {
        button.addEventListener("click", function () {
          applyPreset(button.dataset.range);
        });
      }
    );

    els.scanBtn.addEventListener("click", async function () {
      els.scanBtn.disabled = true;
      try {
        await loadDevices(Number(els.scanDays.value));
      } finally {
        els.scanBtn.disabled = false;
      }
    });

    els.deviceSelect.addEventListener("change", function () {
      els.manualAddress.value = "";
    });

    els.analyzeBtn.addEventListener("click", analyze);
    els.cancelBtn.addEventListener("click", cancelFetch);
    els.resetZoomBtn.addEventListener("click", resetZoom);
  }

  async function init() {
    bindElements();
    setCustomDefaults();
    setupEvents();

    const deepLink = logic.parseDeepLink(window.location.search);
    applyPreset(deepLink.preset);
    if (deepLink.start) {
      els.customStart.value = deepLink.start;
    }
    if (deepLink.end) {
      els.customEnd.value = deepLink.end;
    }

    await loadDevices(null);
    if (!state.devices.length) {
      await loadDevices(1);
    }

    if (deepLink.address) {
      const match = state.devices.find(function (device) {
        return device.address === deepLink.address;
      });
      if (match) {
        els.deviceSelect.value = match.address;
      } else {
        els.manualAddress.value = deepLink.address;
      }
    }

    if (deepLink.autostart && deepLink.address) {
      await analyze();
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
