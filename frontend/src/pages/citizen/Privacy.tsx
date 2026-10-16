import { useState } from "react";
import { Download, Trash2 } from "lucide-react";
import { api, downloadFile } from "../../lib/api";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Confirm, Empty, Notice, PageHead, Q, StatusBadge, useApi } from "../../components/ui";

export function Privacy() {
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const a = useAction();
  const q = useApi<any>(["privacy"], "/api/privacy/requests", { refetchInterval: (qq) => (qq.state.data?.items || []).some((r: any) => ["queued", "processing"].includes(r.status)) ? 4000 : false });
  const [confirmDelete, setConfirmDelete] = useState(false);
  return (
    <>
      <PageHead title={t("privacy.title")} sub={t("privacy.sub")} />
      <div className="grid grid-2" style={{ alignItems: "start" }}>
        <Card title={t("privacy.export")}>
          <p className="small">{t("privacy.exportBody")}</p>
          <Button variant="primary" mutates busy={a.busy} onClick={() => a.run(() => api.post("/api/privacy/requests", { kind: "export" }), { success: t("privacy.exportQueued"), invalidate: [["privacy"]] })}>
            <Download size={15} aria-hidden /> {t("privacy.requestExport")}
          </Button>
        </Card>
        <Card title={t("privacy.deletion")}>
          <p className="small">{t("privacy.deletionBody")}</p>
          <Notice kind="warning">{t("privacy.retained")}</Notice>
          <div style={{ marginTop: 8 }}>
            <Button variant="danger" mutates onClick={() => setConfirmDelete(true)}><Trash2 size={15} aria-hidden /> {t("privacy.requestDeletion")}</Button>
          </div>
        </Card>
      </div>
      <div style={{ marginTop: 16 }} />
      <Card title={t("privacy.requests")}>
        <Q q={q}>
          {(d) => d.items.length === 0 ? <Empty title={t("privacy.none")} /> : (
            <div className="table-wrap"><table>
              <thead><tr><th>{t("common.type")}</th><th>{t("common.status")}</th><th>{t("common.created")}</th><th>{t("privacy.completed")}</th><th>{t("privacy.notes")}</th><th /></tr></thead>
              <tbody>{d.items.map((r: any) => (
                <tr key={r.id}>
                  <td>{en(r.kind)}</td>
                  <td><StatusBadge value={r.status} /></td>
                  <td>{fmtDateTime(r.created_at)}</td>
                  <td>{fmtDateTime(r.completed_at)}</td>
                  <td className="small">{r.notes || "—"}</td>
                  <td>{r.kind === "export" && r.result_object_id && (
                    <Button size="sm" onClick={() => a.run(() => downloadFile(`/api/privacy/requests/${r.id}/download`, "civicbridge-export.zip"))}><Download size={14} aria-hidden /> {t("common.download")}</Button>
                  )}</td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
        </Q>
        <p className="xs muted" style={{ marginTop: 8 }}>{t("privacy.exportExpiry")}</p>
      </Card>
      {confirmDelete && (
        <Confirm title={t("privacy.deletionConfirmTitle")} danger requireText="DELETE" confirmLabel={t("privacy.requestDeletion")}
          body={<><p>{t("privacy.deletionConfirmBody")}</p><Notice kind="warning">{t("privacy.retained")}</Notice></>}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={async () => {
            await a.run(() => api.post("/api/privacy/requests", { kind: "deletion", confirm: "DELETE" }), { success: t("privacy.deletionQueued"), invalidate: [["privacy"]] });
            setConfirmDelete(false);
          }} />
      )}
    </>
  );
}
