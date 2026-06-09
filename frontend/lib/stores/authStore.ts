import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { User } from '../types/user';

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  login: (token: string, user: User) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      token: null,
      isAuthenticated: false,

      login: (token, user) => {
        if (typeof window !== 'undefined') {
          localStorage.setItem('fim_token', token);
          localStorage.setItem('fim_user', JSON.stringify(user));
        }
        set({ token, user, isAuthenticated: true });
      },

      logout: () => {
        if (typeof window !== 'undefined') {
          localStorage.removeItem('fim_token');
          localStorage.removeItem('fim_user');
        }
        set({ token: null, user: null, isAuthenticated: false });
      },
    }),
    {
      name: 'fim-auth',
    }
  )
);
