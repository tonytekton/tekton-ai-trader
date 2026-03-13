import { createClientFromRequest } from 'npm:@base44/sdk@0.8.6';
import pg from 'npm:pg@8.11.3';

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    const body = await req.json();
    const { image_url, notes } = body;

    if (!image_url) {
      return Response.json({ error: 'image_url is required' }, { status: 400 });
    }

    const client = new pg.Client({
      host: Deno.env.get('CLOUD_SQL_HOST'),
      database: Deno.env.get('CLOUD_SQL_DB_NAME'),
      user: Deno.env.get('CLOUD_SQL_DB_USER'),
      password: Deno.env.get('CLOUD_SQL_DB_PASSWORD'),
      port: 5432,
      ssl: false,
    });

    await client.connect();
    await client.query(
      `INSERT INTO ai_reasoning (image_url, notes, source, created_at) VALUES ($1, $2, 'manual', NOW())`,
      [image_url, notes || null]
    );
    await client.end();

    return Response.json({ success: true });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
