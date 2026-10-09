// The page is a reader of the office's event stream, plus one input for the boss.
export type OfficeEvent = { id: number; ts: string; actor: string; kind: string; payload: any };

export async function allEvents(): Promise<OfficeEvent[]> {
  const out: OfficeEvent[] = [];
  let since = 0;
  for (;;) {
    const page: OfficeEvent[] = await (await fetch(`/events?since=${since}`)).json();
    if (!page.length) return out;
    out.push(...page);
    since = page[page.length - 1].id;
  }
}

export function stream(since: number, onEvent: (e: OfficeEvent) => void) {
  const es = new EventSource(`/stream?since=${since}`);
  es.onmessage = (m) => onEvent(JSON.parse(m.data));
  return es;
}

export const getJSON = async (path: string) => {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
};

let token: string | null = null;
try { token = localStorage.getItem("office-token"); } catch { /* private mode: ask each time */ }

export async function whoami(): Promise<string | null> {
  if (!token) return null;
  const r = await fetch("/me", { headers: { Authorization: "Bearer " + token } });
  if (!r.ok) { token = null; return null; }
  return (await r.json()).id;
}

export async function sayAsBoss(text: string): Promise<boolean> {
  if (!token) {
    token = window.prompt("Your office token (kept only in this browser):");
    if (!token) return false;
    try { localStorage.setItem("office-token", token); } catch { /* ignore */ }
  }
  const r = await fetch("/say", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify({ text }),
  });
  if (r.status === 401) { token = null; try { localStorage.removeItem("office-token"); } catch { /* ignore */ } }
  return r.ok;
}
