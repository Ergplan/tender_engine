/** A plain page for a link that cannot be used, or anything else that went wrong. */
export function MessagePage({ title, message }: { title: string; message: string }) {
  return (
    <main className="mx-auto max-w-xl p-10 font-sans text-slate-900">
      <h1 className="text-xl font-semibold">{title}</h1>
      <p role="alert" className="mt-3 text-base text-slate-700">
        {message}
      </p>
    </main>
  );
}
