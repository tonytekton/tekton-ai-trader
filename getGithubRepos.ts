import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    const { accessToken } = await base44.asServiceRole.connectors.getConnection('github');

    const res = await fetch(`https://api.github.com/user/repos?per_page=50`, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: 'application/vnd.github.v3+json',
        'User-Agent': 'Tekton-AI-Trader',
      },
    });

    const repos = await res.json();
    return Response.json({ repos: repos.map(r => r.full_name) });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
