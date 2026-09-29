export type ClinicRole = "rcm_reviewer" | "rcm_lead" | "clinic_admin" | "technical_manager";

export type ClinicSession = {
  user_id: string;
  tenant_id: string;
  role: ClinicRole;
};

async function jsonOrError<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json() as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // Preserve the HTTP status when the server is unreachable or non-JSON.
    }
    throw new Error(message);
  }
  return await response.json() as T;
}

export async function getSession(): Promise<ClinicSession | null> {
  const response = await fetch("/v1/auth/me", { cache: "no-store" });
  if (response.status === 401) return null;
  return jsonOrError<ClinicSession>(response);
}

export async function signIn(tenantId: string, email: string, password: string): Promise<ClinicSession> {
  const response = await fetch("/v1/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ tenant_id: tenantId, email, password }),
  });
  return jsonOrError<ClinicSession>(response);
}

export async function signOut(): Promise<void> {
  await jsonOrError<{ signed_out: boolean }>(await fetch("/v1/auth/logout", { method: "POST" }));
}
