export function StatusChip({ ok, text }: { ok: boolean; text: string }) {
  return (
    <span className={"chip " + (ok ? "chipOk" : "chipBad")}>
      <span className="dot" />
      {text}
    </span>
  );
}
