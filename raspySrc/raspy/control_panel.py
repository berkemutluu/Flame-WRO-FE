import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Robot Control</title>
  <style>
    :root { color-scheme: dark; --bg:#0f1215; --panel:#171d22; --line:#2c3740; --text:#edf4f7; --muted:#9fb0bb; --accent:#55b7ff; --bad:#ff6969; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font:14px/1.35 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    header, main { width:min(1500px, calc(100vw - 24px)); margin:0 auto; }
    header { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:14px 0; border-bottom:1px solid var(--line); }
    h1, h2, h3 { margin:0; letter-spacing:0; }
    h1 { font-size:20px; }
    h2 { font-size:15px; margin-bottom:10px; }
    h3 { font-size:13px; color:var(--muted); margin:12px 0 8px; }
    main { display:grid; grid-template-columns:minmax(360px,1.2fr) minmax(360px,1fr); gap:12px; padding:12px 0 20px; }
    section { border:1px solid var(--line); background:var(--panel); border-radius:8px; padding:12px; }
    .stack { display:grid; gap:12px; align-content:start; }
    .video { width:100%; aspect-ratio:4/3; object-fit:contain; background:#050607; border:1px solid var(--line); border-radius:6px; }
    #previewImg { cursor: crosshair; }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px 12px; }
    .row { display:grid; grid-template-columns:minmax(150px,1fr) minmax(120px,.7fr); align-items:center; gap:8px; padding:4px 0; border-bottom:1px solid rgba(255,255,255,.05); }
    label, .key { color:var(--muted); overflow-wrap:anywhere; }
    input, select, button { border:1px solid var(--line); border-radius:6px; background:#0d1115; color:var(--text); padding:7px 8px; min-width:0; }
    input[type="checkbox"] { width:18px; height:18px; justify-self:end; }
    input[type="color"] { height:34px; padding:2px; }
    button { cursor:pointer; background:#202a33; }
    button:hover { border-color:var(--accent); }
    .buttons { display:flex; flex-wrap:wrap; gap:8px; }
    .value { text-align:right; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
    .hint { color:var(--muted); font-size:13px; margin:0 0 10px; }
    .color-cell { display:grid; grid-template-columns:48px 1fr; gap:8px; align-items:center; }
    .hsv-text { color:var(--muted); font-variant-numeric:tabular-nums; font-size:12px; }
    .calibration { display:grid; gap:8px; }
    .cal-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
    .sample-swatch { display:inline-block; width:16px; height:16px; border:1px solid var(--line); border-radius:4px; vertical-align:-3px; margin-right:6px; }
    details { border-top:1px solid rgba(255,255,255,.08); padding-top:8px; margin-top:8px; }
    details:first-child { border-top:0; padding-top:0; margin-top:0; }
    summary { cursor:pointer; font-weight:650; margin-bottom:8px; }
    #message { color:var(--muted); min-height:20px; }
    .error { color:var(--bad); }
    @media (max-width: 980px) { main { grid-template-columns:1fr; } .grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Robot Control</h1>
      <div id="message"></div>
    </div>
    <div class="buttons">
      <button id="saveBtn" type="button">Save Config</button>
      <button id="reloadBtn" type="button">Reload</button>
    </div>
  </header>
  <main>
    <div class="stack">
      <section>
        <h2>Preview</h2>
        <img id="previewImg" class="video" src="/video_feed" alt="robot camera preview">
      </section>
      <section class="calibration">
        <h2>Color Sampling</h2>
        <p class="hint">Click the preview on a real line or pillar pixel. Then apply that camera sample to a filter range.</p>
        <div class="cal-grid">
          <label>Target
            <select id="sampleTarget">
              <option>ORANGE</option>
              <option>BLUE</option>
              <option>RED</option>
              <option>GREEN</option>
              <option>PINK</option>
              <option>WALL</option>
            </select>
          </label>
          <label>Radius
            <input id="sampleRadius" type="number" min="0" max="30" value="4">
          </label>
          <label>Hue margin
            <input id="sampleHueMargin" type="number" min="0" max="60" value="8">
          </label>
          <label>S/V margin
            <input id="sampleSvMargin" type="number" min="0" max="160" value="35">
          </label>
          <label>Gray margin
            <input id="sampleGrayMargin" type="number" min="0" max="120" value="18">
          </label>
        </div>
        <div id="sampleReadout" class="hint">No sample yet.</div>
        <div class="buttons">
          <button data-sample-action="range" type="button">Apply Last</button>
          <button id="applySamplesBtn" type="button">Apply Samples</button>
          <button data-sample-action="lo" type="button">Set LO</button>
          <button data-sample-action="hi" type="button">Set HI</button>
          <button id="clearSamplesBtn" type="button">Clear Samples</button>
        </div>
      </section>
      <section>
        <h2>Status</h2>
        <div id="statusGrid" class="grid"></div>
      </section>
      <section>
        <h2>Manual Test</h2>
        <div class="buttons">
          <button data-command="STEER" data-value="35">Steer 35</button>
          <button data-command="STEER" data-value="90">Center</button>
          <button data-command="STEER" data-value="145">Steer 145</button>
          <button data-command="DRIVE" data-value="80">Drive 80</button>
          <button data-command="DRIVE" data-value="-80">Reverse 80</button>
          <button data-command="STOP">Stop</button>
        </div>
      </section>
    </div>
    <section>
      <h2>Config</h2>
      <p class="hint">Use Color Sampling first. The color filters use camera HSV thresholds; walls use the grayscale GRAY threshold. Red can wrap around hue 0, so red low/high may look reversed in hue.</p>
      <div id="configFields"></div>
    </section>
  </main>
  <script>
    const message = document.getElementById("message");
    const previewImg = document.getElementById("previewImg");
    const statusGrid = document.getElementById("statusGrid");
    const configFields = document.getElementById("configFields");
    const sampleTarget = document.getElementById("sampleTarget");
    const sampleRadius = document.getElementById("sampleRadius");
    const sampleHueMargin = document.getElementById("sampleHueMargin");
    const sampleSvMargin = document.getElementById("sampleSvMargin");
    const sampleGrayMargin = document.getElementById("sampleGrayMargin");
    const sampleReadout = document.getElementById("sampleReadout");
    let config = {};
    let lastSample = null;
    let sampleSets = {};
    const groups = ["control", "behavior", "pd", "roi", "filters", "serial", "camera", "decision_log", "debug"];
    const defaultOpenGroups = new Set(["control", "behavior", "pd", "serial", "filters"]);
    const statusOrder = ["state", "avoid_phase", "round_dir", "turns_left", "servo_angle", "drive_speed", "correction", "wall_left", "wall_right", "orange", "blue", "pillars", "closest_pillar_color", "closest_pillar_area", "closest_pillar_raw_area", "closest_pillar_x", "closest_pillar_seen", "closest_pillar_held", "serial_port"];
    let configOpenState = loadOpenState();

    function loadOpenState() {
      try {
        return JSON.parse(localStorage.getItem("robotConfigOpenState") || "{}");
      } catch {
        return {};
      }
    }

    function saveOpenState() {
      try {
        localStorage.setItem("robotConfigOpenState", JSON.stringify(configOpenState));
      } catch {
      }
    }

    function rememberOpenStateFromDom() {
      document.querySelectorAll("#configFields details[data-group]").forEach((details) => {
        configOpenState[details.dataset.group] = details.open;
      });
      saveOpenState();
    }

    function setMessage(text, error=false) {
      message.textContent = text || "";
      message.className = error ? "error" : "";
    }

    async function api(path, payload) {
      const options = payload === undefined ? {} : {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      };
      const response = await fetch(path, options);
      const data = await response.json();
      if (!response.ok || data.status === "error") throw new Error(data.message || "Request failed");
      return data;
    }

    function flatten(obj, prefix="") {
      const out = [];
      Object.entries(obj || {}).forEach(([key, value]) => {
        const path = prefix ? `${prefix}.${key}` : key;
        if (value && typeof value === "object" && !Array.isArray(value)) out.push(...flatten(value, path));
        else out.push([path, value]);
      });
      return out;
    }

    function hsvToRgb(h, s, v) {
      h = ((Number(h) || 0) * 2) % 360;
      s = Math.max(0, Math.min(255, Number(s) || 0)) / 255;
      v = Math.max(0, Math.min(255, Number(v) || 0)) / 255;
      const c = v * s;
      const x = c * (1 - Math.abs((h / 60) % 2 - 1));
      const m = v - c;
      let r = 0, g = 0, b = 0;
      if (h < 60) [r, g, b] = [c, x, 0];
      else if (h < 120) [r, g, b] = [x, c, 0];
      else if (h < 180) [r, g, b] = [0, c, x];
      else if (h < 240) [r, g, b] = [0, x, c];
      else if (h < 300) [r, g, b] = [x, 0, c];
      else [r, g, b] = [c, 0, x];
      return [r, g, b].map((channel) => Math.round((channel + m) * 255));
    }

    function rgbToHsvOpenCv(r, g, b) {
      r /= 255; g /= 255; b /= 255;
      const max = Math.max(r, g, b);
      const min = Math.min(r, g, b);
      const d = max - min;
      let h = 0;
      if (d !== 0) {
        if (max === r) h = 60 * (((g - b) / d) % 6);
        else if (max === g) h = 60 * ((b - r) / d + 2);
        else h = 60 * ((r - g) / d + 4);
      }
      if (h < 0) h += 360;
      const s = max === 0 ? 0 : d / max;
      return [Math.round(h / 2), Math.round(s * 255), Math.round(max * 255)];
    }

    function rgbToHex([r, g, b]) {
      return "#" + [r, g, b].map((value) => value.toString(16).padStart(2, "0")).join("");
    }

    function hexToRgb(hex) {
      const clean = hex.replace("#", "");
      return [0, 2, 4].map((index) => parseInt(clean.slice(index, index + 2), 16));
    }

    function isFilterColorPath(path, value) {
      return /^filters\\.[A-Z]+(LO|HI)$/.test(path) && Array.isArray(value) && value.length === 3;
    }

    function previewCoordinates(event) {
      const rect = previewImg.getBoundingClientRect();
      const naturalW = previewImg.naturalWidth;
      const naturalH = previewImg.naturalHeight;
      if (!naturalW || !naturalH) return null;
      const scale = Math.min(rect.width / naturalW, rect.height / naturalH);
      const drawW = naturalW * scale;
      const drawH = naturalH * scale;
      const offsetX = (rect.width - drawW) / 2;
      const offsetY = (rect.height - drawH) / 2;
      const x = (event.clientX - rect.left - offsetX) / scale;
      const y = (event.clientY - rect.top - offsetY) / scale;
      if (x < 0 || y < 0 || x >= naturalW || y >= naturalH) return null;
      return {x: Math.round(x), y: Math.round(y)};
    }

    function updateSampleReadout(sample) {
      const target = sampleTarget.value;
      if (!sampleSets[target]) sampleSets[target] = [];
      if (sample) {
        sample.target = target;
        lastSample = sample;
        sampleSets[target].push(sample);
        sampleSets[target] = sampleSets[target].slice(-32);
      }
      const samples = sampleSets[target];
      const latest = sample || samples[samples.length - 1];
      if (!latest) {
        lastSample = null;
        sampleReadout.textContent = `${target}: no samples yet.`;
        return;
      }
      if (!sample) lastSample = latest;
      sampleReadout.innerHTML = `<span class="sample-swatch" style="background:${latest.hex}"></span>${target} samples=${samples.length} latest x=${latest.x} y=${latest.y} HSV=${latest.hsv.join(", ")} gray=${latest.gray} low=${latest.hsv_low.join(", ")} high=${latest.hsv_high.join(", ")}`;
    }

    function inputFor(path, value) {
      const row = document.createElement("div");
      row.className = "row";
      const label = document.createElement("label");
      label.textContent = path.split(".").slice(1).join(".");
      if (isFilterColorPath(path, value)) {
        const cell = document.createElement("div");
        cell.className = "color-cell";
        const input = document.createElement("input");
        input.type = "color";
        input.value = rgbToHex(hsvToRgb(value[0], value[1], value[2]));
        const readout = document.createElement("span");
        readout.className = "hsv-text";
        readout.textContent = `HSV ${value.join(", ")}`;
        input.addEventListener("change", async () => {
          const next = rgbToHsvOpenCv(...hexToRgb(input.value));
          try {
            await api("/api/config", {path, value: next});
            setMessage(`${path} updated to HSV ${next.join(", ")}`);
            await loadConfig();
          } catch (error) {
            setMessage(error.message, true);
          }
        });
        cell.append(input, readout);
        row.append(label, cell);
        return row;
      }

      let input = document.createElement("input");
      if (typeof value === "boolean") {
        input.type = "checkbox";
        input.checked = value;
      } else if (typeof value === "number") {
        input.type = "number";
        input.step = Number.isInteger(value) ? "1" : "0.01";
        input.value = value;
      } else if (Array.isArray(value)) {
        input.value = JSON.stringify(value);
      } else {
        input.value = value ?? "";
      }
      input.addEventListener("change", async () => {
        let next = input.type === "checkbox" ? input.checked : input.value;
        if (typeof value === "number") next = Number(next);
        else if (Array.isArray(value)) next = JSON.parse(next);
        try {
          await api("/api/config", {path, value: next});
          setMessage(`${path} updated`);
          await loadConfig();
        } catch (error) {
          setMessage(error.message, true);
        }
      });
      row.append(label, input);
      return row;
    }

    function renderConfig() {
      rememberOpenStateFromDom();
      configFields.replaceChildren();
      groups.forEach((group) => {
        if (!(group in config)) return;
        const details = document.createElement("details");
        details.dataset.group = group;
        details.open = Object.prototype.hasOwnProperty.call(configOpenState, group)
          ? Boolean(configOpenState[group])
          : defaultOpenGroups.has(group);
        details.addEventListener("toggle", () => {
          if (!details.isConnected) return;
          configOpenState[group] = details.open;
          saveOpenState();
        });
        const summary = document.createElement("summary");
        summary.textContent = group;
        const fields = document.createElement("div");
        flatten(config[group], group).forEach(([path, value]) => fields.appendChild(inputFor(path, value)));
        details.append(summary, fields);
        configFields.appendChild(details);
      });
    }

    async function loadConfig() {
      config = await api("/api/config");
      renderConfig();
    }

    async function pollStatus() {
      try {
        const status = await api("/api/status");
        statusGrid.replaceChildren();
        const keys = statusOrder.filter((key) => key in status);
        Object.keys(status).forEach((key) => { if (!keys.includes(key)) keys.push(key); });
        keys.forEach((key) => {
          const item = document.createElement("div");
          item.className = "row";
          const k = document.createElement("span");
          k.className = "key";
          k.textContent = key;
          const v = document.createElement("span");
          v.className = "value";
          v.textContent = status[key] ?? "";
          item.append(k, v);
          statusGrid.appendChild(item);
        });
      } catch (error) {
        setMessage(error.message, true);
      }
    }

    document.querySelectorAll("[data-command]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          const payload = {command: button.dataset.command};
          if ("value" in button.dataset) payload.value = Number(button.dataset.value);
          await api("/api/command", payload);
          setMessage(`${payload.command}${payload.value === undefined ? "" : ":" + payload.value} sent`);
        } catch (error) {
          setMessage(error.message, true);
        }
      });
    });
    previewImg.addEventListener("click", async (event) => {
      const coords = previewCoordinates(event);
      if (!coords) return;
      try {
        const data = await api("/api/sample", {
          x: coords.x,
          y: coords.y,
          radius: Number(sampleRadius.value || 4),
        });
        updateSampleReadout(data);
        setMessage(`Sampled HSV ${data.hsv.join(", ")}`);
      } catch (error) {
        setMessage(error.message, true);
      }
    });
    document.querySelectorAll("[data-sample-action]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (!lastSample) {
          setMessage("Click the preview first to take a sample", true);
          return;
        }
        if (sampleTarget.value === "WALL" && button.dataset.sampleAction !== "range") {
          setMessage("Walls use the GRAY threshold; use Apply Last or Apply Samples", true);
          return;
        }
        try {
          const data = await api("/api/apply_sample", {
            target: sampleTarget.value,
            action: button.dataset.sampleAction,
            x: lastSample.x,
            y: lastSample.y,
            radius: Number(sampleRadius.value || 4),
            hue_margin: Number(sampleHueMargin.value || 8),
            sv_margin: Number(sampleSvMargin.value || 35),
            gray_margin: Number(sampleGrayMargin.value || 18),
          });
          if ("gray" in data) setMessage(`${data.target} threshold updated: GRAY ${data.gray}, SAT <= ${data.wall_max_sat}`);
          else setMessage(`${data.target} ${data.action} updated: LO ${data.lo.join(", ")} HI ${data.hi.join(", ")}`);
          await loadConfig();
        } catch (error) {
          setMessage(error.message, true);
        }
      });
    });
    document.getElementById("applySamplesBtn").addEventListener("click", async () => {
      const target = sampleTarget.value;
      const samples = sampleSets[target] || [];
      if (!samples.length) {
        setMessage("Click the preview a few times first", true);
        return;
      }
      try {
        const data = await api("/api/apply_samples", {
          target,
          samples,
          hue_margin: Number(sampleHueMargin.value || 8),
          sv_margin: Number(sampleSvMargin.value || 35),
          gray_margin: Number(sampleGrayMargin.value || 18),
        });
        if ("gray" in data) setMessage(`${data.target} threshold updated from ${samples.length} samples: GRAY ${data.gray}, SAT <= ${data.wall_max_sat}`);
        else setMessage(`${data.target} range updated from ${samples.length} samples: LO ${data.lo.join(", ")} HI ${data.hi.join(", ")}`);
        await loadConfig();
      } catch (error) {
        setMessage(error.message, true);
      }
    });
    document.getElementById("clearSamplesBtn").addEventListener("click", () => {
      sampleSets[sampleTarget.value] = [];
      if (lastSample && sampleTarget.value === lastSample.target) lastSample = null;
      updateSampleReadout(null);
      setMessage(`${sampleTarget.value} samples cleared`);
    });
    sampleTarget.addEventListener("change", () => updateSampleReadout(null));
    document.getElementById("saveBtn").addEventListener("click", async () => {
      try { await api("/api/save", {}); setMessage("Config saved"); }
      catch (error) { setMessage(error.message, true); }
    });
    document.getElementById("reloadBtn").addEventListener("click", () => location.reload());
    loadConfig();
    pollStatus();
    setInterval(pollStatus, 500);
  </script>
</body>
</html>"""


class RobotWebServer:
  def __init__(self, runner, host="0.0.0.0", port=5000):
    self.runner = runner
    self.host = host
    self.port = int(port)
    self.httpd = None
    self.thread = None

  def start(self):
    runner = self.runner

    class Handler(BaseHTTPRequestHandler):
      def log_message(self, fmt, *args):
        return

      def do_GET(self):
        if self.path == "/":
          self.send_bytes(INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/config":
          self.send_json(runner.configloader.config)
        elif self.path == "/api/status":
          self.send_json(runner.status_snapshot())
        elif self.path == "/video_feed":
          self.video_feed()
        else:
          self.send_error(404)

      def do_POST(self):
        payload = self.read_json()
        try:
          if self.path == "/api/config":
            runner.update_config(payload["path"], payload.get("value"))
            self.send_json({"status": "ok"})
          elif self.path == "/api/save":
            runner.configloader.save_config()
            self.send_json({"status": "ok"})
          elif self.path == "/api/command":
            runner.manual_command(payload.get("command"), payload.get("value"))
            self.send_json({"status": "ok"})
          elif self.path == "/api/sample":
            self.send_json(runner.sample_color(payload.get("x"), payload.get("y"), payload.get("radius", 4)))
          elif self.path == "/api/apply_sample":
            self.send_json(runner.apply_color_sample(
              payload.get("target"),
              payload.get("action"),
              payload.get("x"),
              payload.get("y"),
              payload.get("radius"),
              payload.get("hue_margin"),
              payload.get("sv_margin"),
              payload.get("gray_margin"),
            ))
          elif self.path == "/api/apply_samples":
            self.send_json(runner.apply_color_samples(
              payload.get("target"),
              payload.get("samples"),
              payload.get("hue_margin"),
              payload.get("sv_margin"),
              payload.get("gray_margin"),
            ))
          else:
            self.send_error(404)
        except Exception as exc:
          self.send_json({"status": "error", "message": str(exc)}, 400)

      def read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
          return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

      def send_json(self, data, code=200):
        self.send_bytes(json.dumps(data).encode("utf-8"), "application/json", code)

      def send_bytes(self, data, content_type, code=200):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

      def video_feed(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        while True:
          frame = runner.preview_jpeg()
          if frame:
            try:
              self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
              break
          time.sleep(0.05)

    self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
    self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
    self.thread.start()
    print(f"Preview/config page: http://{self.host}:{self.port}")

  def stop(self):
    if self.httpd:
      self.httpd.shutdown()
