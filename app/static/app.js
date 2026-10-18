const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const inr = (n) => (n === null || n === undefined ? "To be decided" : "₹" + Number(n).toLocaleString("en-IN"));
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
};

const OUTCOME = {
  ZERO_LIABILITY_REFUND: ["Full refund, zero liability", "good"],
  COMPENSATION: ["Compensation payable", "good"],
  CUSTOMER_LIABLE: ["Customer liable", "bad"],
  BANK_POLICY_REVIEW: ["Refer to bank policy", "warn"],
  PENDING_CUSTOMER_ACTION: ["Pending customer action", "warn"],
  INCOMPLETE_EVIDENCE: ["Blocked: evidence incomplete", "warn"],
  REJECT_NOT_FRAUD: ["Reject: genuine transaction", "bad"],
};
const CLS = {
  BANK_NEGLIGENCE: "Bank negligence", THIRD_PARTY_BREACH: "Third-party breach", CUSTOMER_NEGLIGENCE: "Customer negligence",
  NOT_FRAUD: "Not fraud", UNDETERMINED: "Undetermined",
};

let current = null;
let data = null;

async function boot() {
  try {
    const h = await api("/api/health");
    const m = $("#mode");
    if (h.llm_mode === "offline") { m.textContent = "Offline mode · rules + templates"; m.className = "chip off"; }
    else { m.textContent = `Gemini live · ${h.model}`; m.className = "chip live"; }
    m.title = `Data: ${h.data_source} · Decisions: ${h.decision_store}`;
  } catch (e) { $("#mode").textContent = "API unreachable"; }
  await loadQueue();
  $("#evalsBtn").onclick = showEvals;
  $("#modalClose").onclick = () => $("#modal").classList.add("hidden");
}

async function loadQueue() {
  const cases = await api("/api/cases");
  $("#caseList").innerHTML = cases.map((c) => `
    <div class="case-card ${c.case_id === current ? "active" : ""}" data-id="${c.case_id}">
      <div class="row"><span class="name">${esc(c.customer)}</span><span class="amt">${inr(c.amount)}</span></div>
      <div class="story">${esc(c.story)}</div>
      <div class="row" style="margin-top:8px">
        <span class="muted small mono">${c.case_id} · ${c.segment}</span>
        <span class="pill ${c.status.toLowerCase()}">${c.status === "ANALYSED" ? "Analysed" : c.status === "NEW" ? "New" : c.status.replace("_", " ").toLowerCase()}</span>
      </div>
      <div class="muted small" style="margin-top:4px">${c.days_left} days left to resolve</div>
    </div>`).join("");
  document.querySelectorAll(".case-card").forEach((el) => (el.onclick = () => openCase(el.dataset.id)));
}

const STEPS = ["Timeline builder", "Intake agent", "Evidence agent", "Rules engine", "Verifier", "Drafter agent"];

function pipelineHTML(trace) {
  return `<div class="pipeline" id="pipeline">${STEPS.map((s, i) => {
    const t = trace ? trace.find((x) => x.agent === s) : null;
    const src = t ? (t.source === "gemini" ? "Gemini" : t.source === "fallback" ? "fallback" : "code") : "";
    return `${i ? '<span class="arrow">›</span>' : ""}<div class="step ${t && t.source === "gemini" ? "gemini" : ""}" data-step="${s}">
      <span class="dot"></span><span>${s}</span><span class="src">${src}${t && t.ms ? " · " + t.ms + "ms" : ""}</span></div>`;
  }).join("")}</div>`;
}

async function openCase(id, refresh = false) {
  current = id;
  document.querySelectorAll(".case-card").forEach((el) => el.classList.toggle("active", el.dataset.id === id));
  const ws = $("#workspace");
  ws.innerHTML = `${pipelineHTML(null)}<div class="loader"><div class="spin"></div>Agents are reviewing case ${id}…</div>`;
  try {
    data = await api(`/api/cases/${id}/analyze${refresh ? "?refresh=true" : ""}`, { method: "POST" });
  } catch (e) {
    ws.innerHTML = `<div class="card">Could not analyse: ${esc(e.message)}</div>`;
    return;
  }
  render();
  const steps = [...document.querySelectorAll(".step")];
  steps.forEach((el, i) => setTimeout(() => el.classList.add("done"), data.cached ? 0 : 180 * i));
  loadQueue();
}

function citeify(text, invalid = []) {
  return esc(text).replace(/\[([A-Z]\d{4}-E\d{2})\]/g, (_, id) => invalid.includes(id)
    ? `<span class="cite bad" title="Verifier: this event does not exist">${id} ✕</span>`
    : `<span class="cite" data-ev="${id}">${id}</span>`);
}

function render() {
  const c = data.case, d = data.decision, v = data.verification, ev = data.evidence.data, tl = data.timeline;
  const [label, tone] = OUTCOME[d.outcome] || [d.outcome, "warn"];
  const bp = tl.break_point;
  const missing = d.missing || [];
  const last = (data.decisions || []).slice(-1)[0];

  $("#workspace").innerHTML = `
    <div class="case-head">
      <div>
        <h1>${esc(c.customer)} <span class="muted mono" style="font-size:14px">· ${c.case_id}</span></h1>
        <div class="meta">${esc(c.segment)} · complaint received ${c.received_on} · reviewed as of ${c.as_of}</div>
      </div>
      <div class="sla"><div class="big">${d.deadline.days_left} days</div><div class="muted small">to resolve (by ${d.deadline.resolve_by})</div>
        <button class="btn ghost" id="rerun" style="margin-top:6px">Re-run agents</button></div>
    </div>

    <div class="card"><h3>Customer complaint</h3><p class="complaint">${esc(c.complaint_text)}</p></div>
    ${pipelineHTML(data.trace)}

    <div class="grid">
      <div class="card">
        <h3>Evidence timeline</h3>
        ${bp ? `<div class="bp">⚑ <b>Break point:</b> ${esc(bp.summary)} <span class="mono">[${bp.event_id}]</span>, <b>${bp.minutes_before_first_txn >= 1440 ? Math.round(bp.minutes_before_first_txn / 1440) + " days" : bp.minutes_before_first_txn + " min"}</b> before the first disputed transaction.</div>` : ""}
        <ul class="timeline">${tl.events.map((e) => `
          <li class="tl ${e.severity}" id="ev-${e.event_id}">
            <span class="id">${e.event_id}</span>
            <span class="t">${e.ts.replace("T", " ").slice(0, 16)}</span><span class="ty">${e.type.replace("_", " ")}</span>
            <div class="s">${esc(e.summary)}${e.attrs.amount ? ` · <b class="mono">${inr(e.attrs.amount)}</b>` : ""}</div>
            <div class="muted small">${esc(e.source)}${e.attrs.device_id ? " · device " + esc(e.attrs.device_id) : ""}</div>
          </li>`).join("")}
        </ul>
      </div>

      <div class="stack">
        <div class="card">
          <div class="verdict-top">
            <div><h3>Recommended decision</h3><div class="outcome ${tone}">${label}</div><div class="cls">Classification: ${CLS[d.classification]}</div></div>
            <span class="badge ${v.status === "verified" ? "ok" : "review"}">${v.status === "verified" ? "✓ Verified" : "Needs review"}</span>
          </div>
          <div class="money">
            <div><div class="k">Disputed</div><div class="v">${inr(d.amounts.gross_loss)}</div></div>
            <div><div class="k">Bank pays</div><div class="v">${inr(d.amounts.bank_pays)}</div></div>
            <div><div class="k">Compensation</div><div class="v">${inr(d.amounts.compensation)}</div></div>
          </div>
          <ul class="findings">${d.findings.map((f) => `
            <li><span class="ic ${f.result}">${f.result === "pass" ? "✓" : f.result === "fail" ? "✕" : "•"}</span>
            <span><b>${esc(f.check)}</b>: ${esc(f.detail)} ${f.evidence.map((x) => `<span class="cite" data-ev="${x}">${x}</span>`).join(" ")}${f.rule ? ` <span class="muted small">(${f.rule})</span>` : ""}</span></li>`).join("")}
          </ul>
          <div class="rules">${d.rules_applied.map((r) => `<span class="rule" title="${esc(data.rules[r].text)}">${r} · ${esc(data.rules[r].title)}</span>`).join("")}</div>
        </div>

        <div class="card">
          <h3>AI investigator's reasoning <span class="muted small">(${data.evidence.source === "gemini" ? "Gemini" : "fallback"})</span></h3>
          <div class="reason">${citeify(ev.reasoning, v.invalid_ids)}</div>
          ${ev.red_flags && ev.red_flags.length ? `<ul class="flags">${ev.red_flags.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
          <div class="muted small" style="margin-top:8px">Verifier: ${v.citations_valid}/${v.citations_checked} citations valid · AI ${v.agreement ? "agrees" : "disagrees"} with rules engine (${CLS[ev.proposed_classification] || ev.proposed_classification})</div>
          ${v.issues.length ? `<ul class="issues">${v.issues.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
          ${ev.questions_for_officer && ev.questions_for_officer.length ? `<div class="muted small" style="margin-top:8px">Questions for officer:</div><ul class="flags">${ev.questions_for_officer.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
        </div>

        <div class="card missing">
          <h3>Missing information</h3>
          ${missing.length ? `<ul>${missing.map((m, i) => `
            <li><input type="checkbox" class="mi" data-item="${esc(m.item)}" id="mi${i}" />
            <label for="mi${i}"><b>${esc(m.item)}</b><div class="why">${esc(m.why)}${m.rule ? " · " + m.rule : ""}</div></label></li>`).join("")}</ul>
            <div class="muted small" style="margin-top:6px">Tick an item once received or consciously waived. Approval stays locked until every item is ticked.</div>`
          : `<div class="allclear">✓ All evidence needed for this decision is on file.</div>`}
        </div>
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <h3>Decision letter <span class="muted small">(${data.letter.source === "gemini" ? "drafted by Gemini" : "template"}, editable)</span></h3>
      <textarea id="letter">${esc(last ? last.letter : data.letter.text)}</textarea>
      <div class="actions">
        <input type="text" id="officer" placeholder="Officer name" style="max-width:200px" value="${esc(last ? last.officer : "")}" />
        <button class="btn primary" id="approve">Approve & send</button>
        <button class="btn warn" id="reqinfo">Request information</button>
        <button class="btn" id="overrideBtn">Override</button>
        <button class="btn ghost" id="download">Download letter</button>
      </div>
      <div class="override" id="overrideBox">
        <select id="ovOutcome">${Object.entries(OUTCOME).map(([k, [l]]) => `<option value="${k}">${l}</option>`).join("")}</select>
        <input type="text" id="ovNote" placeholder="Reason for override (required)" />
        <button class="btn primary" id="ovSave">Save override</button>
      </div>
      <div class="audit" id="audit">${auditHTML(data.decisions)}</div>
    </div>`;

  document.querySelectorAll(".cite").forEach((el) => (el.onclick = () => flash(el.dataset.ev)));
  $("#rerun").onclick = () => openCase(current, true);
  const boxes = [...document.querySelectorAll(".mi")];
  const approve = $("#approve");
  const sync = () => (approve.disabled = boxes.some((b) => !b.checked));
  boxes.forEach((b) => (b.onchange = sync)); sync();
  approve.onclick = () => decide("approve");
  $("#reqinfo").onclick = () => decide("request_info", { note: "Information requested: " + missing.map((m) => m.item).join("; ") });
  $("#overrideBtn").onclick = () => $("#overrideBox").classList.toggle("show");
  $("#ovSave").onclick = () => decide("override", { outcome: $("#ovOutcome").value, note: $("#ovNote").value });
  $("#download").onclick = downloadLetter;
}

function auditHTML(list) {
  if (!list || !list.length) return "";
  return "<b>Audit trail</b>" + list.map((r) => `<div>${r.at.slice(0, 19).replace("T", " ")} UTC · <b>${esc(r.officer)}</b> · ${r.action.replace("_", " ")} · AI: ${r.ai_outcome} → final: ${r.final_outcome}${r.note ? " · " + esc(r.note) : ""}</div>`).join("");
}

function flash(id) {
  const el = document.getElementById("ev-" + id);
  if (!el) return toast(`${id} is not in the evidence`);
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600);
}

async function decide(action, extra = {}) {
  const resolved = [...document.querySelectorAll(".mi")].filter((b) => b.checked).map((b) => b.dataset.item);
  try {
    const r = await api(`/api/cases/${current}/decision`, {
      method: "POST",
      body: JSON.stringify({ action, officer: $("#officer").value || "Officer", letter: $("#letter").value, resolved_items: resolved, note: "", ...extra }),
    });
    data.decisions = r.decisions;
    $("#audit").innerHTML = auditHTML(r.decisions);
    toast(action === "approve" ? "Decision approved and letter queued" : action === "override" ? "Override saved" : "Information request logged");
    loadQueue();
  } catch (e) { toast(e.message); }
}

function downloadLetter() {
  const blob = new Blob([$("#letter").value], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = `${current}-decision-letter.txt`; a.click();
}

function toast(msg) {
  const t = document.createElement("div"); t.className = "toast"; t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), 3200);
}

async function showEvals() {
  $("#modal").classList.remove("hidden");
  $("#modalBody").innerHTML = `<div class="loader"><div class="spin"></div>Running all 8 labelled cases…</div>`;
  try {
    const e = await api("/api/evals");
    const pct = (x) => Math.round(x * 100) + "%";
    $("#modalBody").innerHTML = `
      <h2>Evaluation report</h2>
      <div class="muted">8 labelled cases with known correct outcomes · mode: ${e.llm_mode}</div>
      <div class="kpis">
        <div class="kpi"><div class="v">${pct(e.decision_accuracy)}</div><div class="muted small">Final decisions correct (outcome + amounts)</div></div>
        <div class="kpi"><div class="v">${e.ai_classification_accuracy === null ? "n/a" : pct(e.ai_classification_accuracy)}</div><div class="muted small">AI investigator classified correctly</div></div>
        <div class="kpi"><div class="v">${pct(e.citation_validity)}</div><div class="muted small">AI evidence citations that exist</div></div>
      </div>
      <table><tr><th>Case</th><th>Scenario</th><th>Expected</th><th>Got</th><th>Decision</th><th>AI class.</th><th>Citations</th></tr>
      ${e.rows.map((r) => `<tr><td class="mono">${r.case_id}</td><td>${esc(r.story)}</td><td>${r.expected.outcome}</td><td>${r.got.outcome}</td>
        <td class="${r.outcome_correct && r.amount_correct ? "yes" : "no"}">${r.outcome_correct && r.amount_correct ? "✓" : "✕"}</td>
        <td class="${r.ai_classification_correct ? "yes" : r.ai_classification_correct === null ? "" : "no"}">${r.ai_classification_correct === null ? "n/a" : r.ai_classification_correct ? "✓" : "✕"}</td>
        <td>${r.citations_valid}/${r.citations_checked}</td></tr>`).join("")}
      </table>`;
  } catch (err) { $("#modalBody").innerHTML = `Eval failed: ${esc(err.message)}`; }
}

boot();
