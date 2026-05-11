import axios from "axios";
import { API_BASE_URL } from "../config";

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

// GAP #13: helper to read csrf_token cookie set by the server on login
function getCsrfToken(): string {
  return document.cookie
    .split("; ")
    .find((row) => row.startsWith("csrf_token="))
    ?.split("=")[1] ?? "";
}

api.interceptors.request.use(
  (config) => {
    // Attach JWT token
    const token = localStorage.getItem("fim_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    // GAP #13: attach CSRF token on all state-changing requests
    const csrfToken = getCsrfToken();
    if (csrfToken) {
      config.headers["X-CSRF-Token"] = csrfToken;
    }

    return config;
  },
  (error) => Promise.reject(error)
);

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("fim_token");
      localStorage.removeItem("fim_user");
      window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);
