async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

function toLocal(ts) {
  if (!ts) return "";
  return new Date(ts).toLocaleString();
}

let countsChart, tpuChart;

async function loadCounts() {
  const data = await getJSON("/api/samples?n=500");
  const samples = data.samples || [];
  const labels = samples.map(s => toLocal(s.ts));

  const series = {
    files: samples.map(s => s.files ?? null),
    chunks: samples.map(s => s.chunks ?? null),
    candidates: samples.map(s => s.candidates ?? null),
    clones: samples.map(s => s.clones ?? null),
  };

  const ds = Object.entries(series).map(([k, v]) => ({
    label: k,
    data: v,
    borderWidth: 2,
    borderColor: undefined,
    tension: 0.2,
    spanGaps: true,
  }));

  if (countsChart) countsChart.destroy();
  countsChart = new Chart(document.getElementById("countsChart"), {
    type: "line",
    data: { labels, datasets: ds },
    options: {
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "bottom" } },
      scales: { y: { beginAtZero: true } }
    }
  });

  const meta = document.getElementById("meta");
  meta.textContent = samples.length
    ? `Latest sample: ${toLocal(samples[samples.length-1].ts)}`
    : "No samples yet.";
}

async function loadStatus(){
  const mystatus = await getJSON("/api/status");
  const meta = document.getElementById("mystatus");
  if (mystatus && mystatus.message){
    meta.textContent = `Status: ${mystatus.message}`;
  }
}

async function loadTpuFor(target) {
  const pts = await getJSON(`/api/tpu?target=${encodeURIComponent(target)}&n=1000`);
  const model = await getJSON(`/api/model?target=${encodeURIComponent(target)}`);

  // scatter plot
  const labels = pts.points.map(p => p.N);
  const values = pts.points.map(p => p.tpu);

  if (tpuChart) tpuChart.destroy();
  tpuChart = new Chart(document.getElementById("tpuChart"), {
    type: "scatter",
    data: {
      labels,
      datasets: [{
        label: `${target} — tpu (s/unit)`,
        data: pts.points.map(p => ({ x: p.N, y: p.tpu })),
        pointRadius: 3
      }]
    },
    options: {
      plugins: { legend: { display: true, position: "bottom" } },
      scales: {
        x: { title: { display: true, text: "Total processed (N)" } },
        y: { title: { display: true, text: "time per unit (seconds)" }, beginAtZero: true }
      }
    }
  });

  const modelmeta = document.getElementById("modelMeta");
  if (!model || !model.preferred) {
    modelmeta.textContent = "model: —";
    return;
  }
  const lin = model.linear || {};
  const exp = model.exponential || {};
  modelmeta.textContent = `model: ${model.preferred} | n=${model.n_points} | `
    + `lin R²=${(lin.r2 ?? NaN).toFixed(3)} | exp R²=${(exp.r2 ?? NaN).toFixed(3)}`;
}

document.getElementById("refreshCounts").addEventListener("click", loadCounts);
document.getElementById("refreshTpu").addEventListener("click", () => {
  const target = document.getElementById("targetSelect").value;
  loadTpuFor(target);
});
document.getElementById("targetSelect").addEventListener("change", (e) => {
  loadTpuFor(e.target.value);
});

// initial loads
loadCounts().then(() => {
  const target = document.getElementById("targetSelect").value;
  loadTpuFor(target);
});

// auto-refresh every 3s
setInterval(() => {
  loadCounts();
  const target = document.getElementById("targetSelect").value;
  loadTpuFor(target);
  loadStatus();
}, 3000);
