export type OfficeEvent = { id: number; ts: string; actor: string; kind: string; payload: any };

export async function json<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

export async function history(): Promise<OfficeEvent[]> {
  const out: OfficeEvent[] = [];
  let since = 0;
  for (;;) {
    const page = await json<OfficeEvent[]>(`/events?since=${since}`);
    if (!page.length) return out;
    out.push(...page);
    since = page.at(-1)!.id;
  }
}

export function subscribe(since: number, onEvent: (event: OfficeEvent) => void) {
  const stream = new EventSource(`/stream?since=${since}`);
  stream.onmessage = (message) => onEvent(JSON.parse(message.data));
  return stream;
}

export async function say(text: string) {
  const token = localStorage.getItem("office-token") ?? window.prompt("Office token") ?? "";
  if (!token) return false;
  localStorage.setItem("office-token", token);
  const response = await fetch("/say", { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ text }) });
  return response.ok;
}
