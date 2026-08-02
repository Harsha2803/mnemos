import { SignInComplete } from "@/components/auth/SignInComplete";

export const metadata = {
  title: "Signing in · Mnemos",
};

/** The URL `GET /api/v1/auth/oidc/callback` redirects a completed login to. */
export default function SignInCompletePage() {
  return <SignInComplete />;
}
