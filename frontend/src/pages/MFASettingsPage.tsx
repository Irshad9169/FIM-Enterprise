import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck, ShieldOff, KeyRound, QrCode, CheckCircle } from "lucide-react";

const token = () => localStorage.getItem("fim_token");
const authFetch = (url: string, opts: RequestInit = {}) =>
  fetch(url, { ...opts, headers: { Authorization: `Bearer ${token()}`, "Content-Type": "application/json", ...(opts.headers || {}) } });

export default function MFASettingsPage() {
  const qc = useQueryClient();
  const [step, setStep] = useState<"idle" | "setup" | "confirm" | "disable">("idle");
  const [qrData, setQrData] = useState<{ qr_code: string; secret: string } | null>(null);
  const [code, setCode] = useState("");
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  const showToast = (msg: string, ok: boolean) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 4000);
  };

  const { data: status } = useQuery({
    queryKey: ["mfa-status"],
    queryFn: () => authFetch("/api/v1/mfa/status").then(r => r.json()),
    refetchInterval: 10_000,
  });

  const enableMutation = useMutation({
    mutationFn: () => authFetch("/api/v1/mfa/enable", { method: "POST" }).then(r => r.json()),
    onSuccess: (data) => {
      setQrData({ qr_code: data.qr_code, secret: data.secret });
      setStep("setup");
    },
    onError: () => showToast("Failed to initiate MFA setup", false)
  });

  const confirmMutation = useMutation({
    mutationFn: () => authFetch("/api/v1/mfa/confirm", {
      method: "POST", body: JSON.stringify({ code })
    }).then(async r => { if (!r.ok) { const e = await r.json(); throw new Error(e.detail); } return r.json(); }),
    onSuccess: () => {
      setStep("idle"); setCode(""); setQrData(null);
      qc.invalidateQueries({ queryKey: ["mfa-status"] });
      showToast("MFA enabled successfully — your account is now protected", true);
    },
    onError: (e: any) => showToast(e.message || "Invalid code", false)
  });

  const disableMutation = useMutation({
    mutationFn: () => authFetch("/api/v1/mfa/disable", {
      method: "POST", body: JSON.stringify({ code })
    }).then(async r => { if (!r.ok) { const e = await r.json(); throw new Error(e.detail); } return r.json(); }),
    onSuccess: () => {
      setStep("idle"); setCode("");
      qc.invalidateQueries({ queryKey: ["mfa-status"] });
      showToast("MFA disabled", true);
    },
    onError: (e: any) => showToast(e.message || "Invalid code", false)
  });

  const mfaEnabled = status?.mfa_enabled && status?.mfa_confirmed;

  return (
    <div className="space-y-6 max-w-2xl">
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg border text-sm shadow-lg ${
          toast.ok ? "bg-green-900/90 border-green-700 text-green-200" : "bg-red-900/90 border-red-700 text-red-200"
        }`}>
          {toast.ok ? "✅" : "❌"} {toast.msg}
        </div>
      )}

      {/* Header */}
      <div className="bg-slate-900 p-4 rounded-lg border border-slate-800">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <KeyRound size={20} className="text-blue-400" /> Two-Factor Authentication
        </h1>
        <p className="text-slate-400 text-sm mt-1">
          Add an extra layer of security to your account using a TOTP authenticator app.
        </p>
      </div>

      {/* Status card */}
      <div className={`rounded-lg border p-6 flex items-center justify-between ${
        mfaEnabled
          ? "bg-green-900/10 border-green-800"
          : "bg-slate-900 border-slate-800"
      }`}>
        <div className="flex items-center gap-4">
          {mfaEnabled
            ? <ShieldCheck size={40} className="text-green-400" />
            : <ShieldOff size={40} className="text-slate-500" />}
          <div>
            <div className="text-white font-semibold text-lg">
              {mfaEnabled ? "MFA is enabled" : "MFA is disabled"}
            </div>
            <div className="text-sm text-slate-400">
              {mfaEnabled
                ? "Your account requires a 6-digit code on each login"
                : "Enable MFA to protect your account with Google Authenticator"}
            </div>
          </div>
        </div>
        {step === "idle" && (
          mfaEnabled ? (
            <button onClick={() => setStep("disable")}
              className="px-4 py-2 bg-red-900/30 border border-red-700 text-red-300 rounded-lg text-sm hover:bg-red-900/50">
              Disable MFA
            </button>
          ) : (
            <button onClick={() => enableMutation.mutate()}
              disabled={enableMutation.isPending}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50">
              {enableMutation.isPending ? "Setting up..." : "Enable MFA"}
            </button>
          )
        )}
      </div>

      {/* Setup step — show QR code */}
      {step === "setup" && qrData && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-6 space-y-4">
          <h2 className="text-white font-semibold flex items-center gap-2">
            <QrCode size={18} className="text-blue-400" /> Step 1 — Scan QR Code
          </h2>
          <p className="text-slate-400 text-sm">
            Open <strong className="text-white">Google Authenticator</strong>, tap + and scan this QR code:
          </p>
          <div className="flex justify-center bg-white p-4 rounded-lg w-fit mx-auto">
            <img src={qrData.qr_code} alt="MFA QR Code" className="w-48 h-48" />
          </div>
          <div className="bg-slate-800 rounded p-3">
            <p className="text-xs text-slate-400 mb-1">Or enter this key manually:</p>
            <code className="text-orange-300 font-mono text-sm tracking-widest">{qrData.secret}</code>
          </div>
          <button onClick={() => setStep("confirm")}
            className="w-full py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
            I've scanned it — Enter code →
          </button>
        </div>
      )}

      {/* Confirm step */}
      {step === "confirm" && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-6 space-y-4">
          <h2 className="text-white font-semibold flex items-center gap-2">
            <CheckCircle size={18} className="text-green-400" /> Step 2 — Confirm Setup
          </h2>
          <p className="text-slate-400 text-sm">Enter the 6-digit code from your authenticator app to confirm:</p>
          <input
            type="text" placeholder="000000" maxLength={6} autoFocus
            className="w-full bg-slate-950 border border-slate-700 rounded-lg p-3 text-white text-center text-2xl tracking-widest font-mono outline-none focus:border-blue-500"
            value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
          />
          <div className="flex gap-3">
            <button onClick={() => { setStep("setup"); setCode(""); }}
              className="flex-1 py-2 bg-slate-800 text-slate-300 rounded-lg hover:bg-slate-700">
              ← Back
            </button>
            <button onClick={() => confirmMutation.mutate()}
              disabled={code.length !== 6 || confirmMutation.isPending}
              className="flex-1 py-2 bg-green-700 text-white rounded-lg hover:bg-green-600 disabled:opacity-50">
              {confirmMutation.isPending ? "Verifying..." : "Confirm & Enable"}
            </button>
          </div>
        </div>
      )}

      {/* Disable step */}
      {step === "disable" && (
        <div className="bg-slate-900 border border-red-900 rounded-lg p-6 space-y-4">
          <h2 className="text-white font-semibold">Disable MFA</h2>
          <p className="text-slate-400 text-sm">Enter your current 6-digit code to confirm disabling MFA:</p>
          <input
            type="text" placeholder="000000" maxLength={6} autoFocus
            className="w-full bg-slate-950 border border-slate-700 rounded-lg p-3 text-white text-center text-2xl tracking-widest font-mono outline-none focus:border-red-500"
            value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
          />
          <div className="flex gap-3">
            <button onClick={() => { setStep("idle"); setCode(""); }}
              className="flex-1 py-2 bg-slate-800 text-slate-300 rounded-lg hover:bg-slate-700">
              Cancel
            </button>
            <button onClick={() => disableMutation.mutate()}
              disabled={code.length !== 6 || disableMutation.isPending}
              className="flex-1 py-2 bg-red-700 text-white rounded-lg hover:bg-red-600 disabled:opacity-50">
              {disableMutation.isPending ? "Disabling..." : "Disable MFA"}
            </button>
          </div>
        </div>
      )}

      {/* Info box */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 text-sm text-slate-400 space-y-1">
        <div className="font-semibold text-slate-300 mb-2">Supported authenticator apps:</div>
        <div>• Google Authenticator (iOS / Android)</div>
        <div>• Microsoft Authenticator</div>
        <div>• Authy</div>
        <div>• Any TOTP-compatible app</div>
      </div>
    </div>
  );
}
