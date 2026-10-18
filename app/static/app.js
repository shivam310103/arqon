const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/\bRs\.? ?(?=\d)/g, "₹").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
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
  PENDING_CUSTOMER_ACTION: ["Waiting on customer", "warn"],
  INCOMPLETE_EVIDENCE: ["Blocked: evidence incomplete", "warn"],
  REJECT_NOT_FRAUD: ["Reject: genuine transaction", "danger"],
};
const FAULT = {
  BANK_NEGLIGENCE: "Fault: the bank", THIRD_PARTY_BREACH: "Fault: an outside party", CUSTOMER_NEGLIGENCE: "Fault: the customer",
  NOT_FRAUD: "Not fraud: customer's own payment", UNDETERMINED: "Fault: not yet provable",
};
const SHORT = { BANK_NEGLIGENCE: "Bank", THIRD_PARTY_BREACH: "Outside party", CUSTOMER_NEGLIGENCE: "Customer", NOT_FRAUD: "Not fraud", UNDETERMINED: "Unclear" };
const TYPE = { LOGIN: "Login", DEVICE_BIND: "New phone linked", SIM_SWAP: "SIM swap", OTP_SENT: "OTP sent", AUTH: "Payment approved", TXN: "Money sent",
  BANK_ALERT: "Bank alert", LIVENESS: "Face check", COMPLAINT_BANK: "Reported to bank", COMPLAINT_1930: "Reported to cybercrime helpline", RECOVERY: "Money recovered",
  BREACH_ADVISORY: "Data breach notice", APP_INSTALL: "Screen-sharing app installed", SCAM_WARNING: "Bank scam warning", PHISHING_SMS: "Phishing SMS", CALL_REPORTED: "Scam call", CONTACT_UPDATE: "Mobile number change request" };
const TAG = {
  C1001: ["SIM swap", "t-third"], C1002: ["Fake KYC call", "t-cust"], C1003: ["Card data leak", "t-third"], C1004: ["Remote-access app", "t-cust"],
  C1005: ["Bank error", "t-bank"], C1006: ["Missing log", "t-gap"], C1007: ["Phishing link", "t-cust"], C1008: ["Disputed purchase", "t-gen"],
};
const STATUS = { NEW: ["New", "s-new"], ANALYSED: ["Reviewed", "s-done"], APPROVE: ["Approved", "s-ok"], OVERRIDE: ["Overridden", "s-warn"], REQUEST_INFO: ["Waiting on customer", "s-warn"], AWAITING_CHECKER: ["Needs 2nd approval", "s-warn"] };
const ACTION = { approve: ["Approved", "ok"], override: ["Overridden", "warn"], request_info: ["Documents requested", "warn"] };

let current = null;
let data = null;
let evTypes = {};

async function boot() {
  try {
    const h = await api("/api/health");
    const m = $("#mode");
    m.innerHTML = h.llm_mode === "offline" ? `<span class="dot warn"></span>Offline mode` : `<span class="dot ok"></span>Gemini on ${h.llm_mode.startsWith("vertex") ? "Vertex AI" : "Google AI"}`;
    m.title = `Model: ${h.model} · Evidence: ${h.data_source} · Audit: ${h.decision_store}`;
  } catch (e) { $("#mode").textContent = "API unreachable"; }
  $("#evalsBtn").textContent = "How accurate is the AI?";
  await loadQueue();
  landing();
  $("#evalsBtn").onclick = showEvals;
  $("#modalClose").onclick = () => $("#modal").classList.add("hidden");
}

function landing() {
  $("#workspace").innerHTML = `
    <div class="empty">
      <div class="eyebrow">Fraud compensation desk</div>
      <h1>AI that shows its work.</h1>
      <p>From 1 Jan 2027, Indian banks must refund customers for digital fraud they did not cause, and prove it when they say no. ARQON's Gemini agents investigate each claim, a rules engine applies the law, and a human officer approves.</p>
      <div class="starts">
        <button class="start" data-id="C1001"><b>Start here</b><span>SIM swap: a clear full refund</span></button>
        <button class="start" data-id="C1002"><b>Customer at fault</b><span>Fake KYC call: partial compensation</span></button>
        <button class="start" data-id="C1006"><b>Missing evidence</b><span>The AI refuses to decide</span></button>
      </div>
      <div class="truth">Live: Gemini agents on Vertex AI, BigQuery, Firestore · Synthetic customers · No letters or money actually sent</div>
    </div>`;
  document.querySelectorAll(".start").forEach((b) => (b.onclick = () => openCase(b.dataset.id)));
}

async function loadQueue() {
  const cases = await api("/api/cases");
  $("#caseList").innerHTML = cases.map((c) => {
    const [st, cls] = STATUS[c.status] || [c.status, "s-new"];
    const [tag, tcls] = TAG[c.case_id] || [c.segment, "t-gen"];
    return `
    <button class="q ${c.case_id === current ? "active" : ""}" data-id="${c.case_id}">
      <div class="q-row"><span class="q-name">${esc(c.customer)}</span><span class="q-amt mono">${inr(c.amount)}</span></div>
      <div class="q-row q-meta"><span class="q-tag ${tcls}">${tag}</span><span><span class="sdot ${cls}"></span>${st}</span></div>
    </button>`;
  }).join("");
  document.querySelectorAll(".q").forEach((el) => (el.onclick = () => openCase(el.dataset.id)));
}

const AGENTS = [["Intake agent", "Intake", true], ["Evidence agent", "Investigator", true], ["Rules engine", "Rules engine", false], ["Verifier", "Verifier", false], ["Drafter agent", "Letter drafter", true]];

function cite(id, invalid = []) {
  if (invalid.includes(id)) return `<span class="cite bad" title="The verifier found no such evidence and removed it">${id} not in evidence</span>`;
  return `<button class="cite" data-ev="${id}" title="${id}: show in timeline">${esc(evTypes[id] || id)}</button>`;
}
function citeify(text, invalid = []) {
  return esc(text).replace(/\[((?:[A-Z]\d{4}-E\d{2})(?:\s*,\s*[A-Z]\d{4}-E\d{2})*)\]/g,
    (_, ids) => ids.split(/\s*,\s*/).map((id) => cite(id, invalid)).join(" "));
}

async function openCase(id, refresh = false) {
  current = id;
  document.querySelectorAll(".q").forEach((el) => el.classList.toggle("active", el.dataset.id === id));
  const ws = $("#workspace");
  ws.innerHTML = `<div class="loading"><div class="rail">${AGENTS.map((a) => `<div class="node"><span></span><em>${a[1]}</em></div>`).join("")}</div>
    <p class="muted">Agents are reviewing the claim…</p></div>`;
  let i = 0;
  const tick = setInterval(() => { const n = ws.querySelectorAll(".node"); if (n[i]) n[i].classList.add("on"); i = Math.min(i + 1, n.length - 1); }, 1200);
  try {
    data = await api(`/api/cases/${id}/analyze${refresh ? "?refresh=true" : ""}`, { method: "POST" });
  } catch (e) {
    clearInterval(tick);
    ws.innerHTML = `<div class="section">Could not analyse: ${esc(e.message)}</div>`;
    return;
  }
  clearInterval(tick);
  evTypes = Object.fromEntries(data.timeline.events.map((e) => [e.event_id, TYPE[e.type] || e.type]));
  render();
  loadQueue();
}

function amountsHTML(d) {
  const a = d.amounts;
  const lost = a.gross_loss;
  const cells = [["Customer lost", inr(lost)]];
  if (a.recovered) cells.push(["Recovered", inr(a.recovered)]);
  cells.push(["Bank refunds", inr(a.bank_pays)]);
  if (a.compensation) cells.push([d.outcome === "PENDING_CUSTOMER_ACTION" ? "Compensation (if filed)" : "Compensation", inr(a.compensation)]);
  if (a.bank_pays !== null && a.bank_pays !== undefined && d.outcome !== "PENDING_CUSTOMER_ACTION") {
    cells.push(["Customer bears", inr(Math.max(lost - (a.recovered || 0) - (a.bank_pays || 0) - (a.compensation || 0), 0))]);
  }
  return cells.map(([k, v]) => `<div><span>${k}</span><b class="mono">${v}</b></div>`).join("");
}

function render() {
  const c = data.case, d = data.decision, v = data.verification, ev = data.evidence.data, tl = data.timeline;
  const [label, tone] = OUTCOME[d.outcome] || [d.outcome, "warn"];
  const bp = tl.break_point;
  const missing = d.missing || [];
  const acts = (data.decisions || []).filter((x) => x.action !== "challenge");
  const challenges = (data.decisions || []).filter((x) => x.action === "challenge");
  const last = acts.slice(-1)[0];
  const held = last && last.needs_checker;
  const gemOn = data.evidence.source === "gemini";
  const bpWhen = bp ? (bp.minutes_before_first_txn >= 1440 ? Math.round(bp.minutes_before_first_txn / 1440) + " days" : bp.minutes_before_first_txn + " min") : "";
  const key = tl.events.filter((e) => e.severity !== "normal");
  const showFinal = last && last.action !== "request_info" && !held ? last.final_outcome : null;
  const [fLabel, fTone] = showFinal ? (OUTCOME[showFinal] || [showFinal, "warn"]) : [label, tone];
  const srcOf = (s) => ({ gemini: "Gemini", fallback: "rules fallback", code: "code" }[s] || s);
  const trace = Object.fromEntries((data.trace || []).map((t) => [t.agent, t]));

  $("#workspace").innerHTML = `
    <header class="case-head">
      <div class="ch-main">
        <div class="eyebrow">Claim <span class="mono">${c.case_id}</span> · received ${c.received_on}</div>
        <h1>${esc(c.customer)} <span class="q-tag ${(TAG[c.case_id] || ["", "t-gen"])[1]}">${(TAG[c.case_id] || [""])[0]}</span></h1>
        <details class="quote"><summary>“${esc(c.complaint_text)}”</summary><p>“${esc(c.complaint_text)}”</p></details>
      </div>
      <div class="case-side">
        <span class="sla">Due in <b>${d.deadline.days_left} days</b></span>
        <button class="btn ghost sm" id="rerun">Re-run agents</button>
      </div>
    </header>

    <section class="verdict ${fTone}">
      <div class="v-main">
        <div class="eyebrow">${showFinal ? "Final decision" : "Recommended decision"} · ${FAULT[d.classification]}</div>
        <div class="v-title">${fLabel}</div>
        ${showFinal && showFinal !== d.outcome ? `<div class="v-ovr">Officer overrode the AI's “${label}”. Amounts follow the officer's decision letter.</div>` : `<div class="v-amounts">${amountsHTML(d)}</div>`}
        ${bp ? `<div class="v-bp"><b>Break point:</b> ${esc(bp.summary)}, ${bpWhen} before the money left ${cite(bp.event_id)}</div>` : ""}
      </div>
      <div class="v-side">
        <div class="agree ${v.agreement ? "ok" : "warn"}">
          <div class="agree-h">Who is at fault?</div>
          <div><span>Gemini investigator</span><b>${esc(SHORT[ev.proposed_classification] || ev.proposed_classification)}</b></div>
          <div><span>Rules engine</span><b>${esc(SHORT[d.classification])}</b></div>
          <div class="agree-res">${v.agreement ? "✓ Agree" : "⚠ Disagree: officer must decide"} · ${v.citations_valid}/${v.citations_checked} citations real</div>
        </div>
        <input type="text" id="officer" placeholder="Officer name" value="${esc(last ? last.officer : "")}" />
        <button class="btn primary" id="approve" ${held ? "disabled" : ""}>Approve &amp; send</button>
        <div class="why-locked" id="whyLocked"></div>
        <div class="v-btns"><button class="btn sm" id="reqinfo">Request documents</button><button class="btn sm" id="overrideBtn">Override</button></div>
        <div class="override" id="overrideBox">
          <select id="ovOutcome">${Object.entries(OUTCOME).map(([k, [l]]) => `<option value="${k}">${l}</option>`).join("")}</select>
          <input type="text" id="ovNote" placeholder="Reason (required)" />
          <button class="btn primary sm" id="ovSave">Save override</button>
        </div>
      </div>
    </section>

    <section class="record" id="record">${recordHTML(data.decisions)}</section>

    <div class="agents">${AGENTS.map(([k, name, ai], i) => { const t = trace[k] || {}; return `${i ? '<span class="arr">→</span>' : ""}<div class="agent ${t.source === "gemini" ? "gem" : ""}" title="${t.ms ? (t.ms / 1000).toFixed(1) + "s" : ""}"><b>${name}</b><span>${srcOf(t.source || (ai ? "gemini" : "code"))}${k === "Verifier" ? " · " + v.citations_valid + "/" + v.citations_checked : ""}</span></div>`; }).join("")}<span class="arr">→</span><div class="agent human"><b>Officer</b><span>decides</span></div></div>

    <div class="roles">
      <div><b>Gemini agents</b><span>Investigate, cite evidence, draft. Cannot approve or set amounts.</span></div>
      <div><b>Rules engine</b><span>Computes who pays what from the RBI rules. Same input, same answer.</span></div>
      <div><b>Officer</b><span>Approves, challenges any AI step, or overrides with a written reason.</span></div>
      <div><b>Second officer</b><span>Must confirm any override that pays the customer less.</span></div>
    </div>

    <div class="cols">
      <section class="section">
        <h3>What happened <button class="link" id="tlToggle">Show all ${tl.events.length} events</button></h3>
        <ol class="timeline" id="tl">${tl.events.map((e) => `
          <li class="tl ${e.severity} ${e.severity === "normal" ? "minor" : ""}" id="ev-${e.event_id}">
            <div class="tl-top"><span class="mono t">${e.ts.slice(5, 16).replace("T", " ")}</span><span class="ty">${TYPE[e.type] || e.type}</span>${e.attrs.amount ? `<b class="mono amt">${inr(e.attrs.amount)}</b>` : ""}</div>
            <div class="s">${esc(e.summary)}</div>
          </li>`).join("")}
        </ol>
      </section>

      <div class="right">
        <section class="section gem-card">
          <h3>Gemini investigator <span class="tag ${gemOn ? "gem" : ""}">${gemOn ? "Gemini · Vertex AI" : "rules fallback"}</span></h3>
          <div class="reason">${citeify(ev.reasoning, v.invalid_ids)}</div>
          ${v.issues.length ? `<ul class="issues">${v.issues.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
          ${challengesHTML(challenges.filter((x) => x.step === "evidence"), v.invalid_ids)}
          <div class="challenge" id="chEv">
            <button class="link-btn" data-open="chEv">Not convinced? Challenge the investigator</button>
            <div class="ch-box"><textarea placeholder="e.g. The customer says he never received the OTP. Does the evidence support that?"></textarea>
            <button class="btn sm primary" data-step="evidence">Ask Gemini to re-check</button><span class="note">It must answer from the evidence. It can change its view, not the amounts.</span></div>
          </div>
          ${ev.questions_for_officer && ev.questions_for_officer.length ? `<div class="q-head">Gemini suggests the officer asks</div><ul class="plain">${ev.questions_for_officer.map((x) => `<li>${citeify(x, v.invalid_ids)}</li>`).join("")}</ul>` : ""}
        </section>

        ${missing.length ? `<section class="section missing-card">
          <h3>Missing before approval</h3>
          <ul class="missing">${missing.map((m, i) => `
            <li><input type="checkbox" class="mi" data-item="${esc(m.item)}" id="mi${i}" />
            <label for="mi${i}"><b>${esc(m.item)}</b><span>${esc(m.why)}</span></label></li>`).join("")}</ul>
          <div class="note">Tick an item once received or consciously waived.</div>
        </section>` : ""}

        <section class="section">
          <h3>Rules applied</h3>
          <ul class="findings">${d.findings.filter((f) => f.check !== "Disputed transactions").map((f) => `
            <li><span class="ic ${f.result}">${f.result === "pass" ? "✓" : f.result === "fail" ? "✕" : "•"}</span>
            <div><b>${esc(f.check)}</b> ${esc(f.detail)} ${f.evidence.map((x) => cite(x)).join(" ")}</div></li>`).join("")}
          </ul>
          <div class="rules">${d.rules_applied.map((r) => `<span class="rule" title="${esc(data.rules[r].text)}">${esc(data.rules[r].title)}</span>`).join("")}</div>
        </section>
      </div>
    </div>

    <details class="section letter">
      <summary><h3>Decision letter <span class="tag ${data.letter.source === "gemini" ? "gem" : ""}">${data.letter.source === "gemini" ? "Drafted by Gemini" : "Template"} · editable</span></h3></summary>
      <textarea id="letter">${esc(last && !held ? last.letter : data.letter.text)}</textarea>
      ${challengesHTML(challenges.filter((x) => x.step === "letter"), [])}
      <div class="letter-actions"><button class="btn ghost sm" id="download">Download letter</button>
      <div class="challenge inline" id="chLt"><button class="link-btn" data-open="chLt">Ask Gemini to redraft</button>
        <div class="ch-box"><textarea placeholder="e.g. Simpler Hindi-friendly English, mention the 5-day payout"></textarea>
        <button class="btn sm primary" data-step="letter">Redraft</button></div></div></div>
    </details>`;

  document.querySelectorAll(".cite[data-ev]").forEach((el) => (el.onclick = (e) => { e.preventDefault(); e.stopPropagation(); flash(el.dataset.ev); }));
  $("#rerun").onclick = () => openCase(current, true);
  $("#tlToggle").onclick = () => { const t = $("#tl"); t.classList.toggle("all"); $("#tlToggle").textContent = t.classList.contains("all") ? "Show key events only" : `Show all ${tl.events.length} events`; };
  const boxes = [...document.querySelectorAll(".mi")];
  const approve = $("#approve");
  const sync = () => {
    const open = boxes.filter((b) => !b.checked).length;
    approve.disabled = open > 0;
    $("#whyLocked").textContent = open ? `Locked: ${open} item${open > 1 ? "s" : ""} missing (see “Missing before approval”)` : "";
  };
  boxes.forEach((b) => (b.onchange = sync)); sync();
  approve.onclick = () => decide("approve");
  $("#reqinfo").onclick = () => decide("request_info", { note: missing.length ? "Documents requested: " + missing.map((m) => m.item).join("; ") : "Documents requested" });
  $("#overrideBtn").onclick = () => $("#overrideBox").classList.toggle("show");
  $("#ovSave").onclick = () => decide("override", { outcome: $("#ovOutcome").value, note: $("#ovNote").value });
  $("#download").onclick = downloadLetter;
  document.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => $("#" + b.dataset.open).classList.toggle("show")));
  document.querySelectorAll("[data-step]").forEach((b) => (b.onclick = () => challengeStep(b.dataset.step, b.parentElement.querySelector("textarea").value, b)));
  const ck = $("#checkerOk");
  if (ck) ck.onclick = () => decide("checker_approve", { officer: $("#checkerName").value });
}

function challengesHTML(list, invalid) {
  return list.map((c) => `<div class="ch-item"><div class="ch-q"><b>${esc(c.officer)}</b> challenged: “${esc(c.question)}”</div>
    <div class="ch-a"><b>${c.source === "gemini" ? "Gemini re-checked" : "Re-check"}${c.step === "evidence" ? (c.changed ? ` · changed its view: ${esc(SHORT[c.before] || c.before)} → ${esc(SHORT[c.after] || c.after)}` : " · kept its view") : ""}:</b> ${citeify(c.answer, invalid)}</div></div>`).join("");
}

async function challengeStep(step, question, btn) {
  if (!question.trim()) return toast("Write what you want re-checked");
  btn.disabled = true; btn.textContent = "Gemini is re-checking…";
  try {
    data = await api(`/api/cases/${current}/challenge`, { method: "POST", body: JSON.stringify({ step, question, officer: $("#officer").value || "Officer" }) });
    render();
    toast(step === "letter" ? "Letter redrafted · challenge logged" : "Re-checked · challenge logged in audit trail");
  } catch (e) { toast(e.message); btn.disabled = false; btn.textContent = "Ask Gemini to re-check"; }
}

function recordHTML(all) {
  const list = (all || []).filter((x) => x.action !== "challenge");
  if (!list.length) return "";
  const r = list[list.length - 1];
  if (r.needs_checker) return `
    <div class="rec-head"><span class="rec-badge warn">Held for second approval</span> <b>${esc(r.officer)}</b> wants to change
      <i>${(OUTCOME[r.ai_outcome] || [r.ai_outcome])[0]}</i> to <b>${(OUTCOME[r.final_outcome] || [r.final_outcome])[0]}</b></div>
    <div class="rec-note">Reason: ${esc(r.note)}</div>
    <div class="rec-note">This pays the customer less than the rules engine recommended. Under the RBI framework the bank carries the burden of proof, so a second officer must confirm before anything is sent.</div>
    <div class="checker"><input type="text" id="checkerName" placeholder="Second officer's name" /><button class="btn primary sm" id="checkerOk">Confirm override</button></div>`;
  const [act, tone] = ACTION[r.action] || [r.action, "ok"];
  return `
    <div class="rec-head"><span class="rec-badge ${tone}">${act}</span> by <b>${esc(r.officer)}</b>${r.checker ? ` · confirmed by <b>${esc(r.checker)}</b>` : ""} just now${r.letter_edited ? " · letter edited by officer" : ""}
      ${r.action === "override" ? ` · AI recommended <i>${(OUTCOME[r.ai_outcome] || [r.ai_outcome])[0]}</i>, officer chose <b>${(OUTCOME[r.final_outcome] || [r.final_outcome])[0]}</b>` : ""}</div>
    ${r.note ? `<div class="rec-note">Reason: ${esc(r.note)}</div>` : ""}
    <div class="rec-grid">
      <ol class="rec-steps">
        <li><b>Saved to the audit trail</b><span>${r.saved_to === "firestore" ? "Firestore" : "Audit log"}: AI recommendation, officer's choice, reason and the letter</span></li>
        ${(r.dispatch || []).map((x) => `<li><b>${esc(x.step)}</b><span>${esc(x.to)} · ${esc(x.status.replace(" (simulated)", ""))}</span></li>`).join("")}
      </ol>
      <div><div class="sms"><div class="sms-from">SMS to customer</div>${esc(r.sms || "")}</div></div>
    </div>
    <div class="note">Prototype: letters, SMS and refunds are logged, not sent.</div>`;
}

function flash(id) {
  const el = document.getElementById("ev-" + id);
  if (!el) return toast(`${id} is not in the evidence`);
  $("#tl").classList.add("all");
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
    render();
    $("#record").scrollIntoView({ behavior: "smooth", block: "center" });
    toast(action === "approve" ? "Approved · saved to audit trail" : action === "checker_approve" ? "Second approval recorded · override released" : action === "override" ? ((r.decisions.filter((x) => x.action !== "challenge").slice(-1)[0] || {}).needs_checker ? "Override held for a second officer" : "Override saved · letter rewritten") : "Document request logged");
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
  $("#modalBody").innerHTML = `<div class="loading"><p class="muted">Running all 8 test claims…</p></div>`;
  try {
    const e = await api("/api/evals");
    const pct = (x) => (x === null || x === undefined ? "n/a" : Math.round(x * 100) + "%");
    $("#modalBody").innerHTML = `
      <h2>How accurate is the AI?</h2>
      <p class="muted">8 test claims with known correct answers · ${e.llm_mode === "offline" ? "offline mode" : "Gemini live"}</p>
      <div class="kpis">
        <div class="kpi"><b>${pct(e.decision_accuracy)}</b><span>Final decisions correct, to the rupee</span></div>
        <div class="kpi"><b>${pct(e.ai_classification_accuracy)}</b><span>Gemini investigator found the right fault</span></div>
        <div class="kpi"><b>${pct(e.citation_validity)}</b><span>Gemini's evidence citations that are real</span></div>
      </div>
      <table><tr><th>Claim</th><th>Scenario</th><th>Correct answer</th><th>ARQON</th><th>Gemini</th></tr>
      ${e.rows.map((r) => `<tr><td>${esc((TAG[r.case_id] || [r.case_id])[0])}</td><td>${esc(r.story)}</td><td>${OUTCOME[r.expected.outcome][0]}</td>
        <td class="${r.outcome_correct && r.amount_correct ? "yes" : "no"}">${r.outcome_correct && r.amount_correct ? "✓ correct" : "✕"}</td>
        <td class="${r.ai_classification_correct ? "yes" : r.ai_classification_correct === null ? "" : "no"}">${r.ai_classification_correct === null ? "n/a" : r.ai_classification_correct ? "✓" : "✕ caught by verifier"}</td></tr>`).join("")}
      </table>`;
  } catch (err) { $("#modalBody").innerHTML = `Eval failed: ${esc(err.message)}`; }
}

boot();
