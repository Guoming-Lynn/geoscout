export function safeHost(url: string) {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export function totalTokens(usage: Record<string, number | boolean> | undefined): number {
  return Number(usage?.prompt_tokens || 0) + Number(usage?.completion_tokens || 0);
}

export function nextRunId(runs: { id: string }[] | undefined, current: string | null): string | null {
  if (!runs?.length) return null;
  if (current && runs.some((r) => r.id === current)) return current;
  return runs[0].id;
}

export function runOwnedByProject(
  run: { id: string; project_id?: string } | undefined,
  projectId: string | null,
): boolean {
  if (!run || !projectId) return false;
  return !run.project_id || run.project_id === projectId;
}
