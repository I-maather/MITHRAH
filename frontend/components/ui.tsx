import type { ReactNode } from "react";

export function Card({
  title,
  hint,
  children,
}: {
  title?: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="card">
      {title ? (
        <header className="mb-4">
          <h2 className="text-sm font-semibold text-ink-soft">{title}</h2>
          {hint ? <p className="mt-1 text-xs text-ink-faint">{hint}</p> : null}
        </header>
      ) : null}
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  tone = "neutral",
  sub,
}: {
  label: string;
  value: string;
  tone?: "neutral" | "ok" | "warn" | "stop";
  sub?: string;
}) {
  const toneClass =
    tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : tone === "stop" ? "text-stop" : "text-ink";
  return (
    <div>
      <div className="label">{label}</div>
      <div className={`value ${toneClass}`} dir="ltr">
        {value}
      </div>
      {sub ? <div className="mt-1 text-xs text-ink-faint">{sub}</div> : null}
    </div>
  );
}

export function Pill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "stop";
}) {
  const map = {
    neutral: "bg-surface-sunken text-ink-soft",
    ok: "bg-green-50 text-ok",
    warn: "bg-amber-50 text-warn",
    stop: "bg-red-50 text-stop",
  } as const;
  return <span className={`pill ${map[tone]}`}>{children}</span>;
}

export function Empty({ message }: { message: string }) {
  return (
    <p className="rounded-xl border border-dashed border-line bg-surface-sunken px-4 py-6 text-center text-sm text-ink-faint">
      {message}
    </p>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-stop">
      {message}
    </div>
  );
}

export function Table({
  head,
  rows,
  empty,
}: {
  head: string[];
  rows: ReactNode[][];
  empty: string;
}) {
  if (rows.length === 0) return <Empty message={empty} />;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead>
          <tr className="border-b border-line text-right text-xs text-ink-faint">
            {head.map((h) => (
              <th key={h} className="pb-2 pe-4 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-line/60 last:border-0">
              {row.map((cell, j) => (
                <td key={j} className="py-3 pe-4 align-top">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
