export function logout() {
  localStorage.removeItem("fim_token");
  localStorage.removeItem("fim_user");
}

export interface LoginResponseUser {
  id: string;
  username: string;
  email: string;
  role: string;
  full_name?: string | null;
  permissions?: Record<string, boolean>;
}

export function getCurrentUser(): LoginResponseUser | null {
  const userStr = localStorage.getItem("fim_user");
  return userStr ? JSON.parse(userStr) : null;
}
