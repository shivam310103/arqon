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
  ZERO_LIABILITY_REFUND: ["Full refund, zero liability", "ok"],
  COMPENSATION: ["Compensation payable", "ok"],
  CUSTOMER_LIABLE: ["Customer liable", "danger"],
  BANK_POLICY_REVIEW: ["Refer to bank policy", "warn"],
  PENDING_CUSTOMER_ACTION: ["Pending customer action", "warn"],
  INCOMPLETE_EVIDENCE: ["Blocked: evidence incomplete", "warn"],
  REJECT_NOT_FRAUD: ["Reject: genuine transaction", "danger"],
};
const CLS = {
  BANK_NEGLIGENCE: "Bank negligence", THIRD_PARTY_BREACH: "Third-party breach", CUSTOMER_NEGLIGENCE: "Customer negligence",
  NOT_FRAUD: "Not fraud", UNDETERMINED: "Undetermined",
};
const TYPE = { LOGIN: "Login", DEVICE_BIND: "New device", SIM_SWAP: "SIM swap", OTP_SENT: "OTP sent", AUTH: "Authorisation", TXN: "Transaction",
  BANK_ALERT: "Bank alert", LIVENESS: "Liveness check", COMPLAINT_BANK: "Reported to bank", COMPLAINT_1930: "Reported to 1930", RECOVERY: "Recovery",
  BREACH_ADVISORY: "Breach advisory", APP_INSTALL: "App installed", SCAM_WARNING: "Scam warning", PHISHING_SMS: "Phishing SMS", CALL_REPORTED: "Scam call", CONTACT_UPDATE: "Contact update" };
const STATUS = { NEW: ["New", "s-new"], ANALYSED: ["Analysed", "s-done"], APPROVE: ["Approved", "s-ok"], OVERRIDE: ["Overridden", "s-warn"], REQUEST_INFO: ["Info requested", "s-warn"] };

let current = null;
let data = null;

async function boot() {
  try {
    const h = await api("/api/health");
    const m = $("#mode");
    if (h.llm_mode === "offline") { m.innerHTML = `<span class="dot warn"></span>Offline mode`; }
    else { m.innerHTML = `<span class="dot ok"></span>Gemini on ${h.llm_mode.startsWith("vertex") ? "Vertex AI" : "Google AI"}`; }
    m.title = `Model: ${h.model} · Data: ${h.data_source} · Decisions: ${h.decision_store}`;
  } catch (e) { $("#mode").textContent = "API unreachable"; }
  await loadQueue();
  $("#evalsBtn").onclick = showEvals;
  $("#modalClose").onclick = () => $("#modal").classList.add("hidden");
}

async function loadQueue() {
  const cases = await api("/api/cases");
  $("#caseList").innerHTML = cases.map((c) => {
    const [st, cls] = STATUS[c.status] || [c.status, "s-new"];
    return `
    <button class="q ${c.case_id === current ? "active" : ""}" data-id="${c.case_id}">
      <div class="q-row"><span class="q-name">${esc(c.customer)}</span><span class="q-amt mono">${inr(c.amount)}</span></div>
      <div class="q-story">${esc(c.story)}</div>
      <div class="q-row q-meta"><span><span class="sdot ${cls}"></span>${st}</span><span>${c.days_left}d left · <span class="mono">${c.case_id}</span></span></div>
    </button>`;
  }).join("");
  document.querySelectorAll(".q").forEach((el) => (el.onclick = () => openCase(el.dataset.id)));
}

const STEPS = ["Timeline builder", "Intake agent", "Evidence agent", "Rules engine", "Verifier", "Drafter agent"];

function citeChip(id, invalid = []) {
  return invalid.includes(id)
    ? `<span class="cite bad" title="Verifier: this event does not exist">${id}</span>`
    : `<button class="cite" data-ev="${id}" title="Show in timeline">${id}</button>`;
}
function citeify(text, invalid = []) {
  return esc(text).replace(/\[((?:[A-Z]\d{4}-E\d{2})(?:\s*,\s*[A-Z]\d{4}-E\d{2})*)\]/g,
    (_, ids) => ids.split(/\s*,\s*/).map((id) => citeChip(id, invalid)).join(" "));
}

async function openCase(id, refresh = false) {
  current = id;
  document.querySelectorAll(".q").forEach((el) => el.classList.toggle("active", el.dataset.id === id));
  const ws = $("#workspace");
  ws.innerHTML = `<div class="loading"><div class="rail">${STEPS.map((s) => `<div class="node"><span></span><em>${s}</em></div>`).join("")}</div>
    <p class="muted">Agents are reviewing case ${id}…</p></div>`;
  let i = 0;
  const tick = setInterval(() => { const n = ws.querySelectorAll(".node"); if (n[i]) n[i].classList.add("on"); i = Math.min(i + 1, n.length - 1); }, 900);
  try {
    data = await api(`/api/cases/${id}/analyze${refresh ? "?refresh=true" : ""}`, { method: "POST" });
  } catch (e) {
    clearInterval(tick);
    ws.innerHTML = `<div class="section">Could not analyse: ${esc(e.message)}</div>`;
    return;
  }
  clearInterval(tick);
  render();
  loadQueue();
}

function render() {
  const c = data.case, d = data.decision, v = data.verification, ev = data.evidence.data, tl = data.timeline;
  const [label, tone] = OUTCOME[d.outcome] || [d.outcome, "warn"];
  const bp = tl.break_point;
  const missing = d.missing || [];
  const last = (data.decisions || []).slice(-1)[0];
  const totalMs = (data.trace || []).reduce((a, t) => a + (t.ms || 0), 0);
  const gemSteps = (data.trace || []).filter((t) => t.source === "gemini").length;
  const bpWhen = bp ? (bp.minutes_before_first_txn >= 1440 ? Math.round(bp.minutes_before_first_txn / 1440) + " days" : bp.minutes_before_first_txn + " min") : "";

  $("#workspace").innerHTML = `
    <header class="case-head">
      <div>
        <div class="eyebrow">Case <span class="mono">${c.case_id}</span> · ${esc(c.segment)} · received ${c.received_on}</div>
        <h1>${esc(c.customer)}</h1>
      </div>
      <div class="case-side">
        <span class="sla"><b>${d.deadline.days_left} days</b> left to resolve</span>
        <button class="btn ghost sm" id="rerun">Re-run agents</button>
      </div>
    </header>

    <section class="verdict ${tone}">
      <div class="v-main">
        <div class="eyebrow">Recommended decision · ${CLS[d.classification]}</div>
        <div class="v-title">${label}</div>
        <div class="v-amounts">
          <div><span>Disputed</span><b class="mono">${inr(d.amounts.gross_loss)}</b></div>
          <div><span>Bank pays</span><b class="mono">${inr(d.amounts.bank_pays)}</b></div>
          <div><span>Compensation</span><b class="mono">${inr(d.amounts.compensation)}</b></div>
        </div>
        ${bp ? `<div class="v-bp"><b>Break point:</b> ${esc(bp.summary)}, ${bpWhen} before the first disputed transaction ${citeChip(bp.event_id)}</div>` : ""}
      </div>
      <div class="v-side">
        <div class="v-check ${v.status === "verified" ? "ok" : "warn"}">${v.status === "verified" ? "✓ Verified" : "⚠ Needs review"}</div>
        <div class="v-sub">${v.citations_valid}/${v.citations_checked} citations real · AI ${v.agreement ? "agrees" : "disagrees"} with rules</div>
        <input type="text" id="officer" placeholder="Officer name" value="${esc(last ? last.officer : "")}" />
        <button class="btn primary" id="approve">Approve &amp; send</button>
        <div class="v-btns"><button class="btn sm" id="reqinfo">Request info</button><button class="btn sm" id="overrideBtn">Override</button></div>
        <div class="override" id="overrideBox">
          <select id="ovOutcome">${Object.entries(OUTCOME).map(([k, [l]]) => `<option value="${k}">${l}</option>`).join("")}</select>
          <input type="text" id="ovNote" placeholder="Reason (required)" />
          <button class="btn primary sm" id="ovSave">Save override</button>
        </div>
      </div>
    </section>

    <details class="pipeline">
      <summary><span class="dot ok"></span>${STEPS.length} agents ran · ${gemSteps} on Gemini · ${(totalMs / 1000).toFixed(1)}s · verifier ${v.citations_valid}/${v.citations_checked}</summary>
      <div class="rail done">${STEPS.map((s) => { const t = (data.trace || []).find((x) => x.agent === s) || {}; return `<div class="node on"><span></span><em>${s}</em><small>${t.source === "gemini" ? "Gemini" : t.source === "fallback" ? "fallback" : "code"}${t.ms ? " · " + (t.ms / 1000).toFixed(1) + "s" : ""}</small></div>`; }).join("")}</div>
    </details>

    <div class="cols">
      <section class="section">
        <h3>Evidence timeline</h3>
        <ol class="timeline">${tl.events.map((e) => `
          <li class="tl ${e.severity}" id="ev-${e.event_id}">
            <div class="tl-top"><span class="mono t">${e.ts.slice(5, 16).replace("T", " ")}</span><span class="ty">${TYPE[e.type] || e.type}</span><span class="mono id">${e.event_id.split("-")[1]}</span></div>
            <div class="s">${esc(e.summary)}${e.attrs.amount ? ` <b class="mono amt">${inr(e.attrs.amount)}</b>` : ""}</div>
            <div class="src">${esc(e.source)}${e.attrs.device_id ? " · " + esc(e.attrs.device_id) : ""}</div>
          </li>`).join("")}
        </ol>
      </section>

      <div class="right">
        <section class="section">
          <h3>Why this decision</h3>
          <ul class="findings">${d.findings.map((f) => `
            <li><span class="ic ${f.result}">${f.result === "pass" ? "✓" : f.result === "fail" ? "✕" : "•"}</span>
            <div><b>${esc(f.check)}</b> ${esc(f.detail)} ${f.evidence.map((x) => citeChip(x)).join(" ")}</div></li>`).join("")}
          </ul>
          <div class="rules">${d.rules_applied.map((r) => `<span class="rule" title="${esc(data.rules[r].text)}">${r} · ${esc(data.rules[r].title)}</span>`).join("")}</div>
        </section>

        <section class="section">
          <h3>AI investigator <span class="tag">${data.evidence.source === "gemini" ? "Gemini" : "fallback"}</span></h3>
          <div class="reason">${citeify(ev.reasoning, v.invalid_ids)}</div>
          ${v.issues.length ? `<ul class="issues">${v.issues.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
          ${ev.questions_for_officer && ev.questions_for_officer.length ? `<div class="q-head">Questions for the officer</div><ul class="plain">${ev.questions_for_officer.map((x) => `<li>${citeify(x, v.invalid_ids)}</li>`).join("")}</ul>` : ""}
        </section>

        <section class="section">
          <h3>Missing information</h3>
          ${missing.length ? `<ul class="missing">${missing.map((m, i) => `
            <li><input type="checkbox" class="mi" data-item="${esc(m.item)}" id="mi${i}" />
            <label for="mi${i}"><b>${esc(m.item)}</b><span>${esc(m.why)}</span></label></li>`).join("")}</ul>
            <div class="note">Approval unlocks when every item is received or waived.</div>`
          : `<div class="allclear">✓ All evidence needed for this decision is on file.</div>`}
        </section>

        <details class="section complaint-box">
          <summary><h3>Customer complaint</h3><span class="quote">“${esc(c.complaint_text)}”</span></summary>
          <p>${esc(c.complaint_text)}</p>
        </details>
      </div>
    </div>

    <section class="section letter">
      <h3>Decision letter <span class="tag">${data.letter.source === "gemini" ? "drafted by Gemini" : "template"} · editable</span>
        <button class="btn ghost sm" id="download">Download</button></h3>
      <textarea id="letter">${esc(last ? last.letter : data.letter.text)}</textarea>
      <div class="audit" id="audit">${auditHTML(data.decisions)}</div>
    </section>`;

  document.querySelectorAll(".cite[data-ev]").forEach((el) => (el.onclick = (e) => { e.preventDefault(); e.stopPropagation(); flash(el.dataset.ev); }));
  $("#rerun").onclick = () => openCase(current, true);
  const boxes = [...document.querySelectorAll(".mi")];
  const approve = $("#approve");
  const sync = () => { approve.disabled = boxes.some((b) => !b.checked); approve.title = approve.disabled ? "Resolve missing information first" : ""; };
  boxes.forEach((b) => (b.onchange = sync)); sync();
  approve.onclick = () => decide("approve");
  $("#reqinfo").onclick = () => decide("request_info", { note: missing.length ? "Information requested: " + missing.map((m) => m.item).join("; ") : "Information requested" });
  $("#overrideBtn").onclick = () => $("#overrideBox").classList.toggle("show");
  $("#ovSave").onclick = () => decide("override", { outcome: $("#ovOutcome").value, note: $("#ovNote").value });
  $("#download").onclick = downloadLetter;
}

function auditHTML(list) {
  if (!list || !list.length) return "";
  return `<div class="q-head">Audit trail</div>` + list.map((r) => `<div>${r.at.slice(0, 19).replace("T", " ")} UTC · <b>${esc(r.officer)}</b> · ${r.action.replace("_", " ")} · AI: ${r.ai_outcome} → final: ${r.final_outcome}${r.note ? " · " + esc(r.note) : ""}</div>`).join("");
}

function flash(id) {
  const el = document.getElementById("ev-" + id);
  if (!el) return toast(`${id} is not in the evidence`);
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
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
  $("#modalBody").innerHTML = `<div class="loading"><p class="muted">Running all 8 labelled cases…</p></div>`;
  try {
    const e = await api("/api/evals");
    const pct = (x) => (x === null || x === undefined ? "n/a" : Math.round(x * 100) + "%");
    $("#modalBody").innerHTML = `
      <h2>Evaluation report</h2>
      <p class="muted">8 labelled cases with known correct outcomes · ${e.llm_mode === "offline" ? "offline mode" : "Gemini live"}</p>
      <div class="kpis">
        <div class="kpi"><b>${pct(e.decision_accuracy)}</b><span>Final decisions correct (outcome + amount)</span></div>
        <div class="kpi"><b>${pct(e.ai_classification_accuracy)}</b><span>Gemini investigator classified correctly</span></div>
        <div class="kpi"><b>${pct(e.citation_validity)}</b><span>AI evidence citations that exist</span></div>
      </div>
      <table><tr><th>Case</th><th>Scenario</th><th>Expected</th><th>Got</th><th>Decision</th><th>AI</th><th>Citations</th></tr>
      ${e.rows.map((r) => `<tr><td class="mono">${r.case_id}</td><td>${esc(r.story)}</td><td>${OUTCOME[r.expected.outcome][0]}</td><td>${OUTCOME[r.got.outcome][0]}</td>
        <td class="${r.outcome_correct && r.amount_correct ? "yes" : "no"}">${r.outcome_correct && r.amount_correct ? "✓" : "✕"}</td>
        <td class="${r.ai_classification_correct ? "yes" : r.ai_classification_correct === null ? "" : "no"}">${r.ai_classification_correct === null ? "n/a" : r.ai_classification_correct ? "✓" : "✕ flagged"}</td>
        <td class="mono">${r.citations_valid}/${r.citations_checked}</td></tr>`).join("")}
      </table>`;
  } catch (err) { $("#modalBody").innerHTML = `Eval failed: ${esc(err.message)}`; }
}

boot();
