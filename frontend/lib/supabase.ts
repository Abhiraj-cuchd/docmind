import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

// Standard client for auth operations
export const supabase = createClient(supabaseUrl, supabaseAnonKey);

// Helper to get current session JWT
export async function getAccessToken(): Promise<string | null> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

// Supabase REST headers for the rag schema
export const ragHeaders = {
  'Accept-Profile': 'rag',
  'Content-Profile': 'rag',
};

// Generic Supabase REST fetch with rag schema headers
export async function supabaseFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = await getAccessToken();
  const url = `${supabaseUrl}/rest/v1/${path}`;

  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'apikey': supabaseAnonKey,
      'Authorization': `Bearer ${token ?? supabaseAnonKey}`,
      ...ragHeaders,
      ...(options.headers as Record<string, string> ?? {}),
    },
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Supabase REST error ${res.status}: ${err}`);
  }

  const text = await res.text();
  return text ? JSON.parse(text) : ([] as unknown as T);
}
