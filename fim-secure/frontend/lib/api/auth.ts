import { apiClient } from './client';
import { LoginRequest, LoginResponse } from '../types/user';

export const authApi = {
  login: async (credentials: LoginRequest): Promise<LoginResponse> => {
    const { data } = await apiClient.post<LoginResponse>('/auth/login', credentials);
    return data;
  },

  logout: () => {
    if (typeof window !== 'undefined') {
      localStorage.removeItem('fim_token');
      localStorage.removeItem('fim_user');
    }
  },
};
