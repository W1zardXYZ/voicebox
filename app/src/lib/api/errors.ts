/**
 * Normalizes a FastAPI error `detail` payload into a human-readable message.
 *
 * FastAPI returns `detail` as a plain string for HTTPException, an array of
 * validation error objects for 422 responses, or an arbitrary object for
 * custom handlers. Anything unrecognized falls back to the provided default.
 */
export function formatErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e: Record<string, unknown>) => e.msg || e.message || JSON.stringify(e))
      .join('; ');
  }
  if (detail && typeof detail === 'object') {
    const obj = detail as Record<string, unknown>;
    if (typeof obj.message === 'string') return obj.message;
    return JSON.stringify(detail);
  }
  return fallback;
}
