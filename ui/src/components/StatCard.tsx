export function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="card">
      <div className="cardLabel">{label}</div>
      <div className="cardValue">{value}</div>
      {hint ? <div className="cardHint muted">{hint}</div> : null}
    </div>
  );
}
