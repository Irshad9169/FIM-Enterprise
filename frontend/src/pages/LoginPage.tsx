import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ShieldCheck, Building2 } from "lucide-react";

export default function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  useEffect(() => {
    // Handle SSO callback
    const ssoToken = searchParams.get("sso_token");
    const ssoUser = searchParams.get("sso_user");

    if (ssoToken && ssoUser) {
      localStorage.setItem("fim_token", ssoToken);
      localStorage.setItem("fim_user", ssoUser);
      navigate("/");
    }
  }, [searchParams, navigate]);

  const handleSSO = () => {
    window.location.href = "/api/v1/sso/login";
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-950 via-blue-950 to-slate-950 px-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="flex justify-center mb-8">
          <div className="bg-blue-600 p-4 rounded-2xl shadow-2xl">
            <ShieldCheck className="text-white" size={48} />
          </div>
        </div>

        {/* Title */}
        <h1 className="text-3xl font-bold text-white text-center mb-2">
          FIM Enterprise
        </h1>
        <p className="text-slate-400 text-center mb-12 text-sm">
          File Integrity Monitoring Platform
        </p>

        {/* Card */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 shadow-2xl space-y-6">
          {/* Info Box */}
          <div className="bg-blue-900/20 border border-blue-800/50 rounded-lg p-4">
            <p className="text-blue-200 text-center text-sm">
              Sign in with your corporate credentials
            </p>
          </div>

          {/* SSO Button */}
          <button
            onClick={handleSSO}
            className="w-full py-4 px-4 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-bold transition-colors flex items-center justify-center gap-3 shadow-lg"
          >
            <Building2 size={20} />
            Sign in with Untd SSO
          </button>

          {/* Footer Info */}
          <p className="text-slate-400 text-xs text-center">
            You will be redirected to the corporate identity provider to complete authentication
          </p>
        </div>

        {/* Footer */}
        <p className="text-slate-500 text-xs text-center mt-8">
          © 2026 UNTD — FIM Enterprise Platform
        </p>
      </div>
    </div>
  );
}
