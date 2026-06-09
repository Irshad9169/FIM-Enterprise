import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ShieldCheck, Building2 } from "lucide-react";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  useEffect(() => {
    const ssoToken = searchParams.get("sso_token");
    const ssoUser = searchParams.get("sso_user");

    if (ssoToken && ssoUser) {
      // SAVE BOTH: The token and the actual User Profile (Role/Name)
      localStorage.setItem("fim_token", ssoToken);
      localStorage.setItem("fim_user", ssoUser);
      
      console.log("SSO Login successful, redirecting...");
      navigate("/");
    }

    if (searchParams.get("error")) {
      setError("Corporate SSO authentication failed.");
    }
  }, [searchParams, navigate]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    // Manual login logic remains here...
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-xl p-8 shadow-2xl">
        <div className="flex flex-col items-center mb-8">
          <div className="bg-blue-600 p-3 rounded-lg mb-4">
            <ShieldCheck className="text-white" size={32} />
          </div>
          <h1 className="text-2xl font-bold text-white">FIM Enterprise</h1>
        </div>

        {error && (
          <div className="bg-red-900/20 border border-red-800 text-red-400 p-3 rounded-lg text-sm mb-6">
            {error}
          </div>
        )}

        <form onSubmit={handleLogin} className="space-y-4">
          <input 
            type="text" 
            placeholder="Username" 
            className="w-full bg-slate-950 border border-slate-700 rounded-lg p-3 text-white outline-none" 
            value={username} 
            onChange={e => setUsername(e.target.value)} 
          />
          <input 
            type="password" 
            placeholder="Password" 
            className="w-full bg-slate-950 border border-slate-700 rounded-lg p-3 text-white outline-none" 
            value={password} 
            onChange={e => setPassword(e.target.value)} 
          />
          <button type="submit" className="w-full py-3 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 transition-colors">
            Sign In
          </button>
        </form>

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
      </div>
    </div>
  );
}
