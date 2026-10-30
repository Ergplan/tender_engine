/** The sign-in page: one button, Google. Reviewers who were sent a link do not sign in. */
export function LoginPage({ message }: { message: string | null }) {
  return (
    <main className="mx-auto flex min-h-full max-w-md flex-col justify-center gap-5 p-10 font-sans text-slate-900">
      <div>
        <h1 className="text-2xl font-semibold">Tender Intelligence Engine</h1>
        <p className="mt-2 text-sm text-slate-600">
          Sign in with the Google account of your organisation. Accounts outside the allowed domains are refused.
        </p>
      </div>
      {message && (
        <p role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-[#991b1b]">
          {message}
        </p>
      )}
      <button
        type="button"
        className="min-h-[44px] rounded-md bg-[#0f5f5c] px-4 text-sm font-medium text-white"
        onClick={() => window.location.assign("/api/v1/auth/login")}
      >
        Sign in with Google
      </button>
      <p className="text-xs text-slate-500">
        Were you sent a review link? Open that link instead; it needs no account.
      </p>
      <p className="text-xs text-slate-500">
        Have an access key?{" "}
        <a href="/workspace" className="text-[#0f5f5c] underline">
          Open the tender workspace
        </a>
        .
      </p>
    </main>
  );
}
