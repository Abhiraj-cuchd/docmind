import axios from 'axios';
import { getAccessToken } from './supabase';

// Axios instance that routes through our Next.js API proxy routes
const api = axios.create({
  baseURL: '/',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Inject Bearer token before every request
api.interceptors.request.use(async (config) => {
  const token = await getAccessToken();
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`;
  }
  return config;
});

export default api;
