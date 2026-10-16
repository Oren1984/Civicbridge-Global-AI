import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { ConnectionState, DisconnectReason, Room, RoomEvent, Track, type Participant, type RemoteTrack } from "livekit-client";
import { FileText, Lock, Mic, MicOff, MonitorUp, PhoneOff, Video as VideoIcon, VideoOff } from "lucide-react";
import { api, objectUrl } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Confirm, Empty, Modal, Notice, PageHead, Q, StatusBadge, useApi } from "../../components/ui";

/** One video tile. Re-attaches whenever the underlying track object changes. */
function Tile({ p, source, speaking, label }: { p: Participant; source: Track.Source; speaking: boolean; label: string }) {
  const ref = useRef<HTMLVideoElement>(null);
  const track = p.getTrackPublication(source)?.videoTrack;
  const muted = !track || p.getTrackPublication(source)?.isMuted;
  useEffect(() => {
    const el = ref.current;
    if (!track || !el) return;
    track.attach(el);
    return () => {
      track.detach(el);
    };
  }, [track]);
  return (
    <div className={`tile ${speaking ? "speaking" : ""}`}>
      <video ref={ref} autoPlay playsInline muted={p.isLocal} aria-label={label} style={{ display: muted ? "none" : undefined }} />
      {muted && <div className="avatar" aria-hidden>{(p.name || p.identity).slice(0, 1).toUpperCase()}</div>}
      <span className="cap">{label}{!p.isMicrophoneEnabled && " · 🔇"}</span>
    </div>
  );
}

function SharedDoc({ mid, doc, onClose }: { mid: string; doc: any; onClose: () => void }) {
  const { t } = useI18n();
  const [src, setSrc] = useState<{ url: string; type: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    objectUrl(`/api/meetings/${mid}/shared/${doc.document_id}/preview`)
      .then((r) => {
        url = r.url;
        setSrc(r);
      })
      .catch((e) => setErr(e.message));
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [mid, doc.document_id]);
  return (
    <Modal title={doc.title} onClose={onClose} wide>
      {err && <Notice kind="danger">{err}</Notice>}
      {src && (src.type.startsWith("image/") ? <img className="preview-img" src={src.url} alt={doc.title} /> : <iframe className="preview-frame" sandbox="" src={src.url} title={doc.title} />)}
      <p className="xs muted">{t("room.viewLogged")}</p>
    </Modal>
  );
}

function ShareModal({ mid, onClose }: { mid: string; onClose: () => void }) {
  const { t } = useI18n();
  const en = useEnum();
  const a = useAction();
  const docs = useApi<any>(["documents", "share"], "/api/documents?page_size=100");
  return (
    <Modal title={t("room.share")} onClose={onClose}>
      <p className="small">{t("room.shareNote")}</p>
      <Q q={docs}>
        {(d) => d.items.length === 0 ? <Empty title={t("wallet.none")} /> : (
          <ul className="list">{d.items.map((x: any) => (
            <li key={x.id} className="row-between">
              <span>{x.title} <span className="xs muted">· {en(x.category)}</span></span>
              <Button size="sm" mutates busy={a.busy} disabled={(x.versions.find((v: any) => v.version === x.current_version) || x.versions.at(-1))?.scan_status !== "clean"} onClick={async () => {
                const r = await a.run(() => api.post(`/api/meetings/${mid}/share`, { document_id: x.id }), { success: t("room.shared"), invalidate: [["meeting", mid]] });
                if (r) onClose();
              }}>{t("room.shareBtn")}</Button>
            </li>
          ))}</ul>
        )}
      </Q>
    </Modal>
  );
}

export function MeetingRoom() {
  const { id = "" } = useParams();
  const { me, readOnly } = useAuth();
  const { t, fmtDateTime, timeZone } = useI18n();
  const a = useAction();
  const q = useApi<any>(["meeting", id], `/api/meetings/${id}`, { refetchInterval: 3000 });
  const roomRef = useRef<Room | null>(null);
  const audioBox = useRef<HTMLDivElement>(null);
  const [, bump] = useReducer((x: number) => x + 1, 0);
  const [conn, setConn] = useState<ConnectionState>(ConnectionState.Disconnected);
  const [mediaErr, setMediaErr] = useState<string | null>(null);
  const [ended, setEnded] = useState<string | null>(null);
  const [speakers, setSpeakers] = useState<Set<string>>(new Set());
  const [viewDoc, setViewDoc] = useState<any>(null);
  const [sharing, setSharing] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [removeP, setRemoveP] = useState<any>(null);
  const inv = [["meeting", id], ["meetings"]];

  const disconnect = useCallback(async () => {
    const r = roomRef.current;
    roomRef.current = null;
    if (r) await r.disconnect();
    audioBox.current?.replaceChildren();
    setConn(ConnectionState.Disconnected);
  }, []);

  useEffect(() => () => {
    roomRef.current?.disconnect();
  }, []);

  // Server state wins: if the API says we are no longer admitted (removed, expired, ended), drop the media connection.
  const view = q.data;
  useEffect(() => {
    if (!view || !roomRef.current) return;
    if (view.meeting.status === "ended") {
      setEnded(t("room.endedByHost"));
      disconnect();
    } else if (view.me.status !== "admitted") {
      setEnded(view.me.status === "removed" ? t("room.removed") : t("room.noLongerAdmitted"));
      disconnect();
    }
  }, [view, disconnect, t]);

  const connect = async () => {
    setMediaErr(null);
    setEnded(null);
    const tok = await a.run(() => api.post<{ token: string; url: string; identity: string }>(`/api/meetings/${id}/token`));
    if (!tok) return;
    const room = new Room({ adaptiveStream: true, dynacast: true });
    roomRef.current = room;
    const refresh = () => bump();
    room
      .on(RoomEvent.ConnectionStateChanged, (s) => setConn(s))
      .on(RoomEvent.ParticipantConnected, refresh)
      .on(RoomEvent.ParticipantDisconnected, refresh)
      .on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        if (track.kind === Track.Kind.Audio) audioBox.current?.appendChild(track.attach());
        refresh();
      })
      .on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
        track.detach().forEach((el) => el.remove());
        refresh();
      })
      .on(RoomEvent.TrackMuted, refresh)
      .on(RoomEvent.TrackUnmuted, refresh)
      .on(RoomEvent.LocalTrackPublished, refresh)
      .on(RoomEvent.LocalTrackUnpublished, refresh)
      .on(RoomEvent.ActiveSpeakersChanged, (ps) => setSpeakers(new Set(ps.map((p) => p.identity))))
      .on(RoomEvent.Disconnected, (reason?: DisconnectReason) => {
        audioBox.current?.replaceChildren();
        roomRef.current = null;
        setConn(ConnectionState.Disconnected);
        if (reason === DisconnectReason.PARTICIPANT_REMOVED) setEnded(t("room.removed"));
        else if (reason === DisconnectReason.ROOM_DELETED) setEnded(t("room.endedByHost"));
        else if (reason !== DisconnectReason.CLIENT_INITIATED) setEnded(t("room.connectionLost"));
        q.refetch();
      });
    try {
      await room.connect(tok.url, tok.token);
    } catch (e) {
      roomRef.current = null;
      setMediaErr(t("room.connectFailed", { msg: String((e as Error).message || e) }));
      return;
    }
    try {
      await room.localParticipant.setMicrophoneEnabled(true);
      await room.localParticipant.setCameraEnabled(true);
    } catch {
      setMediaErr(t("room.deviceError"));
    }
    bump();
  };

  const room = roomRef.current;
  const lp = room?.localParticipant;
  const toggle = async (kind: "mic" | "cam" | "screen") => {
    if (!lp) return;
    try {
      if (kind === "mic") await lp.setMicrophoneEnabled(!lp.isMicrophoneEnabled);
      if (kind === "cam") await lp.setCameraEnabled(!lp.isCameraEnabled);
      if (kind === "screen") await lp.setScreenShareEnabled(!lp.isScreenShareEnabled);
    } catch {
      setMediaErr(kind === "screen" ? t("room.screenError") : t("room.deviceError"));
    }
    bump();
  };

  const leave = async () => {
    await disconnect();
    await a.run(() => api.post(`/api/meetings/${id}/leave`), { invalidate: inv });
  };

  return (
    <Q q={q}>
      {(d) => {
        const m = d.meeting;
        const host = d.me.is_host;
        const admitted = d.me.status === "admitted";
        const connected = conn === ConnectionState.Connected || conn === ConnectionState.Reconnecting;
        const nameOf = (identity: string) => d.participants.find((p: any) => p.identity === identity)?.display_name || identity;
        const people: Participant[] = room ? [room.localParticipant, ...Array.from(room.remoteParticipants.values())] : [];
        return (
          <>
            <PageHead title={m.title} sub={<>
              {m.case_reference} · {fmtDateTime(m.scheduled_start)} ({timeZone}){m.timezone !== timeZone && <> · {fmtDateTime(m.scheduled_start, m.timezone)} ({m.timezone})</>} · <StatusBadge value={m.status} />
            </>} actions={<Link to="/meetings">{t("common.back")}</Link>} />
            <Notice kind="info">{t("room.privacy")}</Notice>
            {ended && <Notice kind="warning">{ended}</Notice>}
            {mediaErr && <Notice kind="danger">{mediaErr}</Notice>}
            <div className="room" style={{ marginTop: 16 }}>
              <div className="stack">
                {m.status === "ended" ? <Card><Empty title={t("room.ended")} /></Card> : !connected ? (
                  <Card title={t("room.lobby")}>
                    {host && m.status === "scheduled" && (
                      <><p className="small">{t("room.hostOpen")}</p>
                        <Button variant="primary" mutates busy={a.busy} onClick={() => a.run(() => api.post(`/api/meetings/${id}/open`), { invalidate: inv })}>{t("room.open")}</Button></>
                    )}
                    {!host && m.status === "scheduled" && <p className="small">{t("room.notOpen")}</p>}
                    {!admitted && d.me.status !== "waiting" && d.me.status !== "removed" && m.status === "open" && (
                      <><p className="small">{t("room.askJoin")}</p>
                        <Button variant="primary" mutates busy={a.busy} onClick={() => a.run(() => api.post(`/api/meetings/${id}/join`), { invalidate: inv })}>{t("room.requestJoin")}</Button></>
                    )}
                    {d.me.status === "waiting" && <Notice kind="info" title={t("room.waiting")}>{t("room.waitingBody")}</Notice>}
                    {d.me.status === "removed" && <Notice kind="danger">{t("room.removed")}</Notice>}
                    {admitted && m.status === "open" && (
                      <><p className="small">{t("room.ready")}</p>
                        <Button variant="primary" busy={a.busy} disabled={readOnly} onClick={connect}><VideoIcon size={15} aria-hidden /> {t("room.connect")}</Button>
                        {readOnly && <p className="xs muted">{t("readonly.disabled")}</p>}</>
                    )}
                  </Card>
                ) : (
                  <>
                    {conn === ConnectionState.Reconnecting && <Notice kind="warning">{t("room.reconnecting")}</Notice>}
                    <div className="video-grid" aria-live="polite">
                      {people.map((p) => (
                        <Tile key={p.identity} p={p} source={Track.Source.Camera} speaking={speakers.has(p.identity)} label={p.isLocal ? t("room.you") : nameOf(p.identity)} />
                      ))}
                      {people.filter((p) => p.isScreenShareEnabled).map((p) => (
                        <Tile key={`${p.identity}-screen`} p={p} source={Track.Source.ScreenShare} speaking={false} label={t("room.screenOf", { name: p.isLocal ? t("room.you") : nameOf(p.identity) })} />
                      ))}
                    </div>
                    <div className="controls" role="toolbar" aria-label={t("room.controls")}>
                      <Button className={lp?.isMicrophoneEnabled ? "" : "off"} aria-pressed={!lp?.isMicrophoneEnabled} onClick={() => toggle("mic")}>
                        {lp?.isMicrophoneEnabled ? <Mic size={16} aria-hidden /> : <MicOff size={16} aria-hidden />} {lp?.isMicrophoneEnabled ? t("room.mute") : t("room.unmute")}
                      </Button>
                      <Button className={lp?.isCameraEnabled ? "" : "off"} aria-pressed={!lp?.isCameraEnabled} onClick={() => toggle("cam")}>
                        {lp?.isCameraEnabled ? <VideoIcon size={16} aria-hidden /> : <VideoOff size={16} aria-hidden />} {lp?.isCameraEnabled ? t("room.camOff") : t("room.camOn")}
                      </Button>
                      <Button aria-pressed={!!lp?.isScreenShareEnabled} onClick={() => toggle("screen")}><MonitorUp size={16} aria-hidden /> {lp?.isScreenShareEnabled ? t("room.stopShare") : t("room.shareScreen")}</Button>
                      <Button variant="danger" onClick={leave}><PhoneOff size={16} aria-hidden /> {t("room.leave")}</Button>
                    </div>
                  </>
                )}
                <div ref={audioBox} hidden />
              </div>
              <div className="stack">
                {host && m.status !== "ended" && (
                  <Card title={t("room.waitingRoom")} tight>
                    {d.waiting.length === 0 ? <p className="small muted">{t("room.nobodyWaiting")}</p> : (
                      <ul className="list">{d.waiting.map((p: any) => (
                        <li key={p.id} className="row-between"><span>{p.display_name} <span className="xs muted">· {t(`meetings.role.${p.role}`)}</span></span>
                          <Button size="sm" variant="primary" mutates busy={a.busy} onClick={() => a.run(() => api.post(`/api/meetings/${id}/participants/${p.id}/admit`), { success: t("room.admitted"), invalidate: inv })}>{t("room.admit")}</Button></li>
                      ))}</ul>
                    )}
                  </Card>
                )}
                <Card title={t("room.participants")} tight>
                  {d.participants.length === 0 ? <p className="small muted">{t("room.participantsHidden")}</p> : (
                    <ul className="list">{d.participants.map((p: any) => (
                      <li key={p.id} className="row-between">
                        <span>{p.display_name}{p.identity === d.me.identity && ` (${t("room.you")})`} <span className="xs muted">· {t(`meetings.role.${p.role}`)}</span></span>
                        <span className="row"><StatusBadge value={p.status} />
                          {host && p.identity !== d.me.identity && ["admitted", "waiting", "invited"].includes(p.status) && m.status !== "ended" && (
                            <Button size="sm" variant="danger" mutates onClick={() => setRemoveP(p)}>{t("room.remove")}</Button>
                          )}</span>
                      </li>
                    ))}</ul>
                  )}
                  {host && m.status !== "ended" && <div style={{ marginTop: 8 }}><Button size="sm" variant="danger" mutates onClick={() => setConfirmEnd(true)}>{t("room.end")}</Button></div>}
                </Card>
                <Card title={t("room.documents")} tight actions={connected && me?.active?.workspace === "citizen" && admitted ? <Button size="sm" mutates onClick={() => setSharing(true)}>{t("room.share")}</Button> : undefined}>
                  {d.shared_documents.length === 0 ? <p className="small muted">{t("room.noDocs")}</p> : (
                    <ul className="list">{d.shared_documents.map((s: any) => (
                      <li key={s.document_id}>
                        {s.can_view ? (
                          <div className="row-between"><span><FileText size={14} aria-hidden /> {s.title}</span><Button size="sm" disabled={!admitted} onClick={() => setViewDoc(s)}>{t("common.view")}</Button></div>
                        ) : (
                          <div><Lock size={14} aria-hidden /> <span className="small">{t("room.restrictedDoc")}</span><div className="xs muted">{s.reason}</div></div>
                        )}
                      </li>
                    ))}</ul>
                  )}
                </Card>
                <p className="xs muted">{t("room.recordingDisabled")}</p>
              </div>
            </div>
            {viewDoc && <SharedDoc mid={id} doc={viewDoc} onClose={() => setViewDoc(null)} />}
            {sharing && <ShareModal mid={id} onClose={() => setSharing(false)} />}
            {removeP && <Confirm title={t("room.removeTitle")} danger confirmLabel={t("room.remove")} body={<p>{t("room.removeBody", { name: removeP.display_name })}</p>}
              onCancel={() => setRemoveP(null)} onConfirm={async () => { await a.run(() => api.post(`/api/meetings/${id}/participants/${removeP.id}/remove`), { success: t("room.removedOk"), invalidate: inv }); setRemoveP(null); }} />}
            {confirmEnd && <Confirm title={t("room.endTitle")} danger confirmLabel={t("room.end")} body={<p>{t("room.endBody")}</p>}
              onCancel={() => setConfirmEnd(false)} onConfirm={async () => { await a.run(() => api.post(`/api/meetings/${id}/end`), { invalidate: inv }); setConfirmEnd(false); await disconnect(); }} />}
          </>
        );
      }}
    </Q>
  );
}
