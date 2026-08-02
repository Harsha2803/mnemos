import { Suspense } from "react";

import { SignInForm } from "@/components/auth/SignInForm";

export const metadata = {
  title: "Sign in · Mnemos",
};

/**
 * Outside the `(app)` route group on purpose: this is the one screen that must
 * render for somebody with no session, so it is not behind the auth boundary
 * and does not carry the app shell. A sign-in form inside a sidebar full of
 * destinations nobody can reach is a screen that argues with itself.
 *
 * `Suspense` because `useSearchParams` opts the subtree into client rendering,
 * and Next requires the boundary to be explicit rather than implied.
 */
export default function SignInPage() {
  return (
    <Suspense fallback={null}>
      <SignInForm />
    </Suspense>
  );
}
