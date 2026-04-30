import { NextRequest, NextResponse } from 'next/server';

const API_ENDPOINT = process.env.NEXT_PUBLIC_API_ENDPOINT!;

/**
 * GET /api/document-url/[docId]
 * Fetches a presigned GET URL from Lambda so the browser can load the PDF.
 * Lambda endpoint: GET {API_ENDPOINT}/document/{docId}/url
 */
export async function GET(
  req: NextRequest,
  ctx: RouteContext<'/api/document-url/[docId]'>
) {
  const authHeader = req.headers.get('Authorization');
  if (!authHeader) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { docId } = await ctx.params;

  try {
    const upstream = await fetch(`${API_ENDPOINT}/document/${docId}/url`, {
      method: 'GET',
      headers: {
        Authorization: authHeader,
      },
    });

    if (!upstream.ok) {
      const err = await upstream.text();
      return NextResponse.json(
        { error: `Failed to get document URL: ${err}` },
        { status: upstream.status }
      );
    }

    const data = await upstream.json();
    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    console.error(`[/api/document-url/${docId}] error:`, err);
    return NextResponse.json({ error: 'Internal Server Error' }, { status: 500 });
  }
}
