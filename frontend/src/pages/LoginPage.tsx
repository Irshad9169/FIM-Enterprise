import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ShieldCheck, Building2, KeyRound } from "lucide-react";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [step, setStep] = useState<"credentials" | "mfa">("credentials");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  useEffect(() => {
    const ssoToken = searchParams.get("sso_token");
    const ssoUser = searchParams.get("sso_user");
    if (ssoToken && ssoUser) {
      localStorage.setItem("fim_token", ssoToken);
      localStorage.setItem("fim_user", ssoUser);
      navigate("/");
    }
    if (searchParams.get("error")) {
      setError("Corporate SSO authentication failed.");
    }
  }, [searchParams, navigate]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password })
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || "Invalid username or password");
        return;
      }
      if (data.mfa_required) {
        // Password OK but MFA required — show TOTP input
        setStep("mfa");
        return;
      }
      // Normal login — store token and redirect
      localStorage.setItem("fim_token", data.access_token);
      localStorage.setItem("fim_user", JSON.stringify(data.user));
      navigate("/");
    } catch {
      setError("Connection error — please try again");
    } finally {
      setLoading(false);
    }
  };

  const handleMFA = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/v1/mfa/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, code: mfaCode })
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || "Invalid MFA code");
        setMfaCode("");
        return;
      }
      localStorage.setItem("fim_token", data.access_token);
      localStorage.setItem("fim_user", JSON.stringify(data.user));
      navigate("/");
    } catch {
      setError("Connection error — please try again");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-xl p-8 shadow-2xl">
        <div className="flex flex-col items-center mb-8">
          <div className="bg-blue-600 p-3 rounded-lg mb-4">
            <ShieldCheck className="text-white" size={32} />
          </div>
          <h1 className="text-2xl font-bold text-white">FIM Enterprise</h1>
          {step === "mfa" && (
            <p className="text-slate-400 text-sm mt-2">Two-factor authentication required</p>
          )}
        </div>

        {error && (
          <div className="bg-red-900/20 border border-red-800 text-red-400 p-3 rounded-lg text-sm mb-6">
            {error}
          </div>
        )}

        {step === "credentials" ? (
          <form onSubmit={handleLogin} className="space-y-4">
            <input
              type="text" placeholder="Username" autoFocus
              className="w-full bg-slate-950 border border-slate-700 rounded-lg p-3 text-white outline-none focus:border-blue-500"
              value={username} onChange={e => setUsername(e.target.value)}
            />
            <input
              type="password" placeholder="Password"
              className="w-full bg-slate-950 border border-slate-700 rounded-lg p-3 text-white outline-none focus:border-blue-500"
              value={password} onChange={e => setPassword(e.target.value)}
            />
            <button type="submit" disabled={loading || !username || !password}
              className="w-full py-3 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 disabled:opacity-50 transition-colors">
              {loading ? "Signing in..." : "Sign In"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleMFA} className="space-y-4">
            <div className="bg-blue-900/20 border border-blue-800 rounded-lg p-4 text-center">
              <KeyRound size={24} className="text-blue-400 mx-auto mb-2" />
              <p className="text-blue-300 text-sm">Enter the 6-digit code from your authenticator app</p>
            </div>
            <input
              type="text" placeholder="000000" maxLength={6} autoFocus
              className="w-full bg-slate-950 border border-slate-700 rounded-lg p-3 text-white outline-none focus:border-blue-500 text-center text-2xl tracking-widest font-mono"
              value={mfaCode} onChange={e => setMfaCode(e.target.value.replace(/\D/g, ''))}
            />
            <button type="submit" disabled={loading || mfaCode.length !== 6}
              className="w-full py-3 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 disabled:opacity-50 transition-colors">
              {loading ? "Verifying..." : "Verify Code"}
            </button>
            <button type="button" onClick={() => { setStep("credentials"); setMfaCode(""); setError(""); }}
              className="w-full py-2 text-slate-400 hover:text-white text-sm">
              ← Back to login
            </button>
          </form>
        )}

        {step === "credentials" && (
          <>
            <div className="relative my-8">
              <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-slate-800"></div></div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-slate-900 px-2 text-slate-500">Or use Corporate Identity</span>
              </div>
            </div>
            <button
              onClick={() => window.location.href = "/api/v1/sso/login"}
              className="w-full py-3 bg-slate-800 text-white rounded-lg font-bold border border-slate-700 hover:bg-slate-700 transition-colors flex items-center justify-center gap-3"
            >
              <Building2 size={20} className="text-blue-400" />
              Sign in with Untd SSO
            </button>
          </>
        )}
      </div>
    </div>
  );
}
