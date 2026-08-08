import { vi } from "vitest";

/**
 * The App Router, as a test double.
 *
 * `usePathname` happens to return `null` outside a router context, which is why
 * F0's tests never needed this; `useRouter` **throws**, so the moment a
 * component navigates it needs a router to navigate with. Rather than stub it
 * per file, one double is installed globally in `vitest.setup.ts` and its calls
 * are readable here — which is also what lets a test assert *where* an
 * unauthenticated visit was sent, rather than only that it left.
 */
export const navigation = {
  pathname: "/",
  searchParams: new URLSearchParams(),
  // `useParams()` — route segments, e.g. `{ sessionId: "..." }` for
  // `/chat/[sessionId]`. Empty by default because most tests render a page
  // with no dynamic segment; `visit` is how a chat test supplies one.
  params: {} as Record<string, string>,
  push: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
  back: vi.fn(),
  forward: vi.fn(),
  prefetch: vi.fn(),
};

export function resetNavigation(): void {
  navigation.pathname = "/";
  navigation.searchParams = new URLSearchParams();
  navigation.params = {};
  navigation.push.mockClear();
  navigation.replace.mockClear();
  navigation.refresh.mockClear();
  navigation.back.mockClear();
  navigation.forward.mockClear();
  navigation.prefetch.mockClear();
}

/** Put the test on a given URL, the way a real visit would. */
export function visit(
  pathname: string,
  query = "",
  params: Record<string, string> = {},
): void {
  navigation.pathname = pathname;
  navigation.searchParams = new URLSearchParams(query);
  navigation.params = params;
}
