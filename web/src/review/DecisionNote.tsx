/** A remark to go with an approval or a "not in document": the reviewer keeps the value
 * and says something about it (owner's review of 2026-10-06, four such cases). Stored on
 * the approval row and shown on the decision line; it is not a correction. */
export function DecisionNote({
  value,
  onChange,
  onSubmit,
}: {
  value: string;
  onChange: (value: string) => void;
  /** Enter in the box: approve with the note. */
  onSubmit: () => void;
}) {
  return (
    <form
      className="mt-1.5"
      onClick={(event) => event.stopPropagation()}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <input
        autoFocus
        type="text"
        data-testid="decision-note"
        aria-label="Note to go with your decision"
        placeholder="Note to go with your decision (kept with it, not a correction)"
        className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </form>
  );
}
