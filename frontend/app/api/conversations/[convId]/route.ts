import { NextRequest, NextResponse } from 'next/server';

const API_ENDPOINT = process.env.NEXT_PUBLIC_API_ENDPOINT!;

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ convId: string }> }
) {
  const authHeader = request.headers.get('Authorization');
  if (!authHeader?.startsWith('Bearer ')) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { convId } = await params;
  if (!convId) {
    return NextResponse.json({ error: 'convId is required' }, { status: 400 });
  }

  try {
    const res = await fetch(`${API_ENDPOINT}/conversations/${convId}`, {
      method: 'DELETE',
      headers: {
        Authorization: authHeader,
        'Content-Type': 'application/json',
      },
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ error: 'Internal Server Error' }, { status: 500 });
  }
}
