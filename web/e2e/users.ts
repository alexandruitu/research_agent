export const PASSWORD = "e2e-test-password-1"; // keep in step with scripts/e2e_server.py
export const ROLES = ["viewer", "member", "admin"] as const;
export type Role = (typeof ROLES)[number];
export const EMAIL: Record<Role, string> = {
  viewer: "viewer@example.org",
  member: "member@example.org",
  admin: "admin@example.org",
};
export const auth = (role: Role) => `e2e/.auth/${role}.json`;
