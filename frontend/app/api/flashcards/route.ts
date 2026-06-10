import { NextRequest, NextResponse } from 'next/server';

const API_ENDPOINT = process.env.NEXT_PUBLIC_API_ENDPOINT!;

export async function GET(req: NextRequest) {
  const authHeader = req.headers.get('Authorization');
  if (!authHeader) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { searchParams } = new URL(req.url);
  const params = new URLSearchParams();
  if (searchParams.get('conversation_id')) params.set('conversation_id', searchParams.get('conversation_id')!);
  if (searchParams.get('document_id')) params.set('document_id', searchParams.get('document_id')!);
  if (searchParams.get('deck_id')) params.set('deck_id', searchParams.get('deck_id')!);

  try {
    const upstream = await fetch(`${API_ENDPOINT}/flashcards?${params}`, {
      method: 'GET',
      headers: { Authorization: authHeader },
    });

    const data = await upstream.json();
    return NextResponse.json(data, { status: upstream.status });
  } catch (err) {
    console.error('[/api/flashcards] error:', err);
    return NextResponse.json({ error: 'Internal Server Error' }, { status: 500 });
  }
}
