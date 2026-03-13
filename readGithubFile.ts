import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    const { accessToken } = await base44.asServiceRole.connectors.getConnection('github');

    const { owner, repo, path, offset = 0, length = 4000 } = await req.json();

    const res = await fetch(`https://api.github.com/repos/${owner}/${repo}/contents/${path}`, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: 'application/vnd.github.v3+json',
        'User-Agent': 'Tekton-AI-Trader',
      },
    });

    if (!res.ok) {
      const err = await res.text();
      return Response.json({ error: err }, { status: res.status });
    }

    const data = await res.json();
    const content = atob(data.content.replace(/\n/g, ''));
    const total = content.length;
    const chunk = content.slice(offset, offset + length);
    return Response.json({ content: chunk, total, offset, length });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
