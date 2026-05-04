// app/api/document-url/route.ts
import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'  // ← server client

const API_ENDPOINT = process.env.NEXT_PUBLIC_API_ENDPOINT

export async function GET(request: NextRequest) {
  const authHeader = request.headers.get('Authorization')

  if (!authHeader?.startsWith('Bearer ')) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const documentId = request.nextUrl.searchParams.get('document_id')

  if (!documentId) {
    return NextResponse.json(
      { error: 'document_id is required' },
      { status: 400 }
    )
  }

  try {
    const res = await fetch(
      `${API_ENDPOINT}/document-url?document_id=${documentId}`,
      {
        headers: {
          'Authorization': authHeader,
          'Content-Type':  'application/json',
        },
        cache: 'no-store',
      }
    )

    const data = await res.json()
    return NextResponse.json(data, { status: res.status })

  } catch (e) {
    return NextResponse.json(
      { error: 'Failed to fetch document URL' },
      { status: 500 }
    )
  }
}