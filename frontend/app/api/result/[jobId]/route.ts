import { NextRequest, NextResponse } from 'next/server';

const API_ENDPOINT = process.env.NEXT_PUBLIC_API_ENDPOINT!;

export async function GET(
  req: NextRequest,
  ctx: RouteContext<'/api/result/[jobId]'>
) {
  const authHeader = req.headers.get('Authorization');
  if (!authHeader) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { jobId } = await ctx.params;

  try {
    const upstream = await fetch(`${API_ENDPOINT}/result/${jobId}`, {
      method: 'GET',
      headers: {
        Authorization: authHeader,
      },
    });

    const data = await upstream.json();
    return NextResponse.json(data, { status: upstream.status });
  } catch (err) {
    console.error(`[/api/result/${jobId}] error:`, err);
    return NextResponse.json({ error: 'Internal Server Error' }, { status: 500 });
  }
}
