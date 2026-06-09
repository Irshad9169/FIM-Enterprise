import { api } from "./client";

interface LoginRequest {
  username: string;
  password: string;
}

interface LoginResponseUser {
  id: string;
  username: string;
  email: string;
  role: string;
  full_name?: string | null;
  permissions?: Record<string, boolean>;
}

interface LoginResponse {
  access_token: string;
  token_type: string;
  user: LoginResponseUser;
}

export async function login(req: LoginRequest): Promise<LoginResponse> {
  const { data } = await api.post<LoginResponse>("/auth/login", req);
  localStorage.setItem("fim_token", data.access_token);
  localStorage.setItem("fim_user", JSON.stringify(data.user));
  return data;
}

export function logout() {
  localStorage.removeItem("fim_token");
  localStorage.removeItem("fim_user");
}

export function getCurrentUser(): LoginResponseUser | null {
  const userStr = localStorage.getItem("fim_user");
  return userStr ? JSON.parse(userStr) : null;
}
