import React, { useCallback, useEffect, useRef, useState } from "react";
import MemoBody from "./MemoBody";
import {
  chat, getApproval, getMemo, getUser, login, logout, pollRun, resubmit, startRun,
  type RunSnapshot, type User,
} from "./api";

const CASES = [
  { id: "CR-2026-00451", client: "Acme Industrial Holdings", type: "Renewal Decision Memo", amount: 5000000 },
  { id: "CR-2026-00452", client: "Blue Harbor Logistics", type: "Renewal Decision Memo", amount: 2000000 },
  { id: "CR-2026-00453", client: "Cedar Peak Materials", type: "Renewal Decision Memo", amount: 2000000 },
];

export default function App() {
  const [user, setUser] = useState<User | null>(getUser());
  const [snap, setSnap] = useState<RunSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(true);
  const [memo, setMemo] = useState<string | null>(null);
  const runIdRef = useRef<string | null>(null);
  const terminalRef = useRef(false);

  // Read ?run= (dashboard deep link from approval email)
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const run = p.get("run");
    if (run && run.startsWith("approval:")) {
      const rid = run.slice(9);
      // open the governance view by requesting the run behind this approval
      getApproval(rid).then((a) => loadRun(a.run_id)).catch(() => { /* noop */ });
    } else if (run) {
      loadRun(run);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadRun(runId: string) {
    try {
      setSnap(await pollRun(runId, setSnap));
      runIdRef.current = runId;
    } catch (e) { setError((e as Error).message); }
  }

  const onLogin = async (u: string, p: string) => {
    setError(null);
    try {
      setUser(await login(u, p));
    } catch (e) { setError((e as Error).message); }
  };

  const onGenerate = useCallback(async () => {
    if (!user) return;
    const caseId = document.getElementById("caseId") as HTMLSelectElement;
    const amountEl = document.getElementById("amount") as HTMLInputElement;
    const amount = parseInt(amountEl.value || "0", 10);
    if (!amount || amount <= 0) { setError("Enter a valid loan amount"); return; }
    setError(null);
    setBusy(true);
    setMemo(null);
    try {
      // stream live progress into the workflow panel while the governed run
      // executes; resolves as soon as the run reaches a stable state
      // (terminal OR AWAITING_APPROVAL).
      const snap = await startRun(caseId.value, amount, setSnap);
      runIdRef.current = snap.run!.run_id;
      // show the memo once the run has produced it (after approval / completion)
      const refreshMemo = async () => {
        try {
          const m = await getMemo(snap.run!.run_id);
          setMemo(m.memo_md || null);
        } catch { /* memo not ready yet */ }
      };
      if (snap.run?.status === "COMPLETED") await refreshMemo();
    } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }, [user]);

  const onResubmit = async () => {
    if (!snap?.approval_request) return;
    setError(null);
    try {
      const r = await resubmit(snap.approval_request.request_id);
      await loadRun(r.run_id);
    } catch (e) { setError((e as Error).message); }
  };

  const onChat = async (text: string) => {
    try {
      const r = await chat(text);
      setChatMsgs((m) => [...m, { who: "agent", text: r.reply }]);
    } catch (e) {
      setChatMsgs((m) => [...m, { who: "agent", text: `error: ${(e as Error).message}` }]);
    }
  };
  const [chatMsgs, setChatMsgs] = useState<{ who: "user" | "agent"; text: string }[]>([]);
  const [chatText, setChatText] = useState("");

  if (!user) {
    return <Login onLogin={onLogin} error={error} />;
  }

  const run = snap?.run ?? null;
  const isTerminal = run ? ["COMPLETED", "REJECTED", "FAILED"].includes(run.status) : false;
  const isAwaiting = run?.status === "AWAITING_APPROVAL";

  return (
    <div className="app">
      <Header user={user} onLogout={logout} />
      <div className="layout">
        <div className="main">
          {error && <div className="banner err">⚠ {error}</div>}

          {isAwaiting && snap?.approval_request && (
            <div className="gov">
              <h2>Governance Review In Progress</h2>
              <div>Request ID: <span className="rid">{snap.approval_request.request_id}</span></div>
              <p>The governance team has been notified. This page will automatically continue once
                approval is granted, or you can re-submit manually after approval.</p>
              <div className="actions">
                <button className="btn-primary btn-green" onClick={onResubmit} disabled={busy}>
                  ↻ Re-submit (Approved)
                </button>
              </div>
            </div>
          )}

          {run ? (
            <>
              {!isTerminal && (
                <div className="banner"><span className="spin">◌</span> Governed run in progress…</div>
              )}
              {run.status === "COMPLETED" && (
                <div className="banner ok">✔ Loan verification completed</div>
              )}
              {run.status === "REJECTED" && (
                <div className="banner err">✖ Loan verification rejected</div>
              )}
              {run.status === "FAILED" && (
                <div className="banner err">✖ Run failed: {run.fail_reason}</div>
              )}

              <div className="card">
                <h2>Workflow Progress</h2>
                <ul className="steps">
                  {(snap?.steps ?? []).map((s) => (
                    <li key={s.seq} className={s.state}>
                      <span className={`dot ${s.state}`}>
                        {s.state === "done" ? "✓" : s.state === "active" ? <span className="pulse" /> : s.state === "failed" ? "✖" : ""}
                      </span>
                      <span className="lbl">{s.name}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {memo && (
                <div className="card memo">
                  <h2>Generated Memo</h2>
                  <MemoBody md={memo} />
                </div>
              )}

              {isTerminal && (
                <div className="card">
                  <h2>Run Summary</h2>
                  <div className="kv"><span className="k">Status</span>
                    <span className={`status-pill ${run.status === "COMPLETED" ? "ok" : "err"}`}>{run.status}</span></div>
                  <div className="kv"><span className="k">Case ID</span><span>{run.case_id}</span></div>
                  <div className="kv"><span className="k">Run ID</span><span>{run.run_id}</span></div>
                  <div className="kv"><span className="k">Requested by</span><span>{run.requested_by} ({run.requested_emp_id})</span></div>
                  {run.approved_by && <div className="kv"><span className="k">Approved by</span><span>{run.approved_by} ({run.approval_role ?? "Senior Credit Officer"})</span></div>}
                </div>
              )}

              {isTerminal && (
                <div className="card">
                  <h2>Audit Trail</h2>
                  <ul className="audit-list">
                    {(snap?.audit ?? []).map((a, i) => (
                      <li key={i}>
                        <span className="n">{i + 1}</span>
                        <span>{a.action} — {a.detail}</span>
                        <span className="ts">{fmtTs(a.ts)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          ) : (
            <CaseForm cases={CASES} onGenerate={onGenerate} busy={busy} />
          )}
        </div>
        {chatOpen && (
          <div className="chat">
            <div className="chat-head">
              <span>Agent Chat</span>
              <span style={{ cursor: "pointer" }} onClick={() => setChatOpen(false)}>✕</span>
            </div>
            <div className="chat-body">
              {chatMsgs.length === 0 && <div className="placeholder">Ask questions about cases, clients, or credit policies. You can also ask the agent to generate a memo.</div>}
              {chatMsgs.map((m, i) => (
                <div key={i} className={`msg ${m.who}`}>
                  <div className="who">{m.who === "user" ? user.name : "credit-memo-agent"}</div>
                  <div className="bubble">{m.text}</div>
                </div>
              ))}
            </div>
            <div className="chat-input">
              <input value={chatText} placeholder="Ask about a case, client, or request a memo…"
                onChange={(e) => setChatText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && chatText.trim()) { onChat(chatText.trim()); setChatText(""); } }} />
              <button className="send" onClick={() => { if (chatText.trim()) { onChat(chatText.trim()); setChatText(""); } }}>➤</button>
            </div>
          </div>
        )}
      </div>
      {!chatOpen && <button onClick={() => setChatOpen(true)}
        style={{ position: "fixed", right: 16, bottom: 16, background: "#16294f", color: "#fff", border: 0, borderRadius: 8, padding: "8px 14px", cursor: "pointer" }}>💬 Agent Chat</button>}
    </div>
  );
}

function Header({ user, onLogout }: { user: User; onLogout: () => void }) {
  const initials = user.name.split(" ").map((s) => s[0]).join("").slice(0, 2).toUpperCase();
  return (
    <div className="header">
      <div className="brand"><span className="gear">⚙</span> Credit Risk Portal</div>
      <div className="userbox">
        <div className="avatar">{initials}</div>
        <div style={{ textAlign: "right" }}>
          <div>{user.name}</div>
          <div style={{ fontSize: 11, opacity: .7 }}>{user.employee_id} · {user.department}</div>
        </div>
        <button className="logout" onClick={onLogout}>Logout</button>
      </div>
    </div>
  );
}

function Login({ onLogin, error }: { onLogin: (u: string, p: string) => void; error: string | null }) {
  const [u, setU] = useState("nick");
  const [p, setP] = useState("analyst123");
  return (
    <div className="app" style={{ alignItems: "center", justifyContent: "center", background: "#0f1e3a" }}>
      <div className="card" style={{ width: 380, boxShadow: "0 20px 50px rgba(0,0,0,.4)" }}>
        <h2 style={{ textAlign: "center" }}>Credit Risk Portal</h2>
        <div className="section-label" style={{ textAlign: "center" }}>SIGN IN</div>
        {error && <div className="banner err" style={{ marginBottom: 12 }}>{error}</div>}
        <div className="field"><label>Username</label>
          <input value={u} onChange={(e) => setU(e.target.value)} /></div>
        <div className="field"><label>Password</label>
          <input type="password" value={p} onChange={(e) => setP(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onLogin(u, p)} /></div>
        <button className="btn-primary" style={{ width: "100%", justifyContent: "center" }} onClick={() => onLogin(u, p)}>
          Sign In
        </button>
        <div className="how" style={{ marginTop: 14 }}>
          Demo credentials — Analyst: <b>nick / analyst123</b> · Officer: <b>sarah / officer123</b>
        </div>
      </div>
    </div>
  );
}

function CaseForm({ cases, onGenerate, busy }: { cases: typeof CASES; onGenerate: () => void; busy: boolean }) {
  const [sel, setSel] = useState(cases[0].id);
  const c = cases.find((x) => x.id === sel)!;
  return (
    <>
      <div className="card">
        <h2>Analyst Portal</h2>
        <div className="section-label">SESSION INFORMATION</div>
        <div className="row"><span className="k">Logged in as</span><span className="v">Nick Johnson</span></div>
        <div className="row"><span className="k">Role</span><span className="v">Risk Analyst</span></div>
        <div className="row"><span className="k">Department</span><span className="v">Credit Risk</span></div>
        <div className="row"><span className="k">Employee ID</span><span className="v">E102938</span></div>
      </div>
      <div className="card">
        <h2>Case Selection</h2>
        <div className="field"><label>Case ID</label>
          <select id="caseId" value={sel} onChange={(e) => setSel(e.target.value)}>
            {cases.map((x) => <option key={x.id} value={x.id}>{x.id}</option>)}
          </select>
        </div>
        <div className="row"><span className="k">Client</span><span className="v">{c.client}</span></div>
        <div className="row"><span className="k">Type</span><span className="v">{c.type}</span></div>
        <div className="field"><label>Amount (USD)</label>
          <input id="amount" type="number" defaultValue={c.amount} min={1000} step={1000} /></div>
        <button className="btn-primary" onClick={onGenerate} disabled={busy}>
          {busy ? "Generating…" : "▶ Generate renewal decision memo"}
        </button>
      </div>
      <div className="how">
        <b>HOW THIS WORKS</b><br />
        When you click <b>Generate</b>, the portal passes your authenticated identity and the selected
        case ID to the platform. The agent then retrieves data from approved systems (CRM, credit
        exposure, transactions, compliance, prior memos), drafts the memo, and submits it for policy
        evaluation. If approval is required, the workflow pauses until a senior officer approves.
      </div>
    </>
  );
}

function fmtTs(ts: string | null | undefined): string {
  if (!ts) return "";
  try {
    return new Date(ts).toISOString().replace("T", " ").slice(0, 19) + "Z";
  } catch { return ts; }
}
