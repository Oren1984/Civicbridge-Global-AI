import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Bell } from "lucide-react";
import { api } from "../../lib/api";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Empty, PageHead, Pagination, Q, Tabs, useApi } from "../../components/ui";

function Preferences() {
  const { t } = useI18n();
  const en = useEnum();
  const a = useAction();
  const q = useApi<any>(["notif-prefs"], "/api/notifications/preferences");
  const [rows, setRows] = useState<any[] | null>(null);
  useEffect(() => {
    if (q.data) setRows(q.data.items);
  }, [q.data]);
  const set = (cat: string, k: "in_app" | "email", v: boolean) => setRows((r) => (r || []).map((x) => (x.category === cat ? { ...x, [k]: v } : x)));
  return (
    <Q q={q}>
      {() => (
        <>
          <div className="table-wrap"><table>
            <thead><tr><th>{t("common.category")}</th><th>{t("notif.inApp")}</th><th>{t("notif.email")}</th></tr></thead>
            <tbody>{(rows || []).map((p) => (
              <tr key={p.category}>
                <td>{en(p.category)}{p.locked && <span className="xs muted"> · {t("notif.lockedSecurity")}</span>}</td>
                <td><input type="checkbox" aria-label={`${en(p.category)} ${t("notif.inApp")}`} checked={p.in_app} disabled={p.locked} onChange={(e) => set(p.category, "in_app", e.target.checked)} /></td>
                <td><input type="checkbox" aria-label={`${en(p.category)} ${t("notif.email")}`} checked={p.email} onChange={(e) => set(p.category, "email", e.target.checked)} /></td>
              </tr>
            ))}</tbody>
          </table></div>
          <p className="xs muted">{t("notif.emailNote")}</p>
          <div className="form-actions">
            <Button variant="primary" mutates busy={a.busy} onClick={() => a.run(() => api.put("/api/notifications/preferences", (rows || []).map(({ category, in_app, email }) => ({ category, in_app, email }))),
              { success: t("notif.saved"), invalidate: [["notif-prefs"]] })}>{t("common.save")}</Button>
          </div>
        </>
      )}
    </Q>
  );
}

export function Notifications() {
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const a = useAction();
  const [tab, setTab] = useState<"all" | "unread" | "prefs">("all");
  const [page, setPage] = useState(1);
  const q = useApi<any>(["notifications", tab, page], tab === "prefs" ? null : `/api/notifications?page=${page}&page_size=20${tab === "unread" ? "&unread=true" : ""}`);
  const read = (id: string) => a.run(() => api.post(`/api/notifications/${id}/read`), { silent: true, invalidate: [["notifications"]] });
  return (
    <>
      <PageHead title={t("notif.title")} actions={<Button mutates busy={a.busy} onClick={() => a.run(() => api.post("/api/notifications/read-all"), { success: t("notif.allRead"), invalidate: [["notifications"]] })}>{t("notif.readAll")}</Button>} />
      <Card>
        <Tabs label={t("notif.title")} value={tab} onChange={(v) => { setTab(v); setPage(1); }} tabs={[
          { id: "all", label: t("notif.all") },
          { id: "unread", label: t("notif.unread"), count: q.data?.unread },
          { id: "prefs", label: t("notif.prefs") },
        ]} />
        {tab === "prefs" ? <Preferences /> : (
          <Q q={q}>
            {(d) => d.items.length === 0 ? <Empty title={t("notif.none")} icon={<Bell size={32} />} /> : (
              <>
                <ul className="list">{d.items.map((n: any) => (
                  <li key={n.id} style={{ fontWeight: n.read_at ? 400 : 600 }}>
                    <div className="row-between">
                      <span>
                        {n.link ? <Link to={n.link} onClick={() => !n.read_at && read(n.id)}>{n.title}</Link> : n.title}
                        {!n.read_at && <span className="badge b-info" style={{ marginInlineStart: 6 }}>{t("notif.new")}</span>}
                      </span>
                      <span className="row"><span className="xs muted">{en(n.kind)} · {fmtDateTime(n.created_at)}</span>
                        {!n.read_at && <Button size="sm" onClick={() => read(n.id)}>{t("notif.markRead")}</Button>}</span>
                    </div>
                    {n.body && <div className="small" style={{ fontWeight: 400 }}>{n.body}</div>}
                  </li>
                ))}</ul>
                <Pagination meta={d.meta} onPage={setPage} />
              </>
            )}
          </Q>
        )}
      </Card>
    </>
  );
}
