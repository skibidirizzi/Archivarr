export function StatusChip({ ok, text, logo, href }: { ok: boolean; text: string; logo?: string; href?: string }) {
  const content = (
    <>
      <span className="dot" />
      {logo && (
        <img 
          src={logo} 
          alt="" 
          style={{ 
            width: '16px', 
            height: '16px', 
            marginRight: '6px',
            verticalAlign: 'middle'
          }} 
        />
      )}
      {text}
    </>
  );

  if (href) {
    return (
      <a 
        href={href} 
        target="_blank" 
        rel="noopener noreferrer" 
        className={"chip " + (ok ? "chipOk" : "chipBad")}
        style={{ textDecoration: 'none', cursor: 'pointer', color: 'inherit' }}
      >
        {content}
      </a>
    );
  }

  return (
    <span className={"chip " + (ok ? "chipOk" : "chipBad")}>
      {content}
    </span>
  );
}
