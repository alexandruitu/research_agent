import { useRef, useState, type DragEvent } from "react";

import { ApiError } from "../../api/client";
import { useDeletePaperFile, usePaperFiles, useReviewSettings, useUploadPaperFile } from "../../api/hooks";
import { hasRole, type PaperFileOut } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";

export const sizeText = (bytes: number) => (bytes >= 1 << 20 ? `${(bytes / (1 << 20)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);
const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");

/** Checks the browser can make before sending: a PDF, not empty, under the limit. The server checks again. */
export function checkFile(file: File, limitMb: number): string | null {
  const pdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!pdf) return `${file.name} is not a PDF. Only PDF files can be uploaded.`;
  if (file.size === 0) return `${file.name} is empty.`;
  if (file.size > limitMb * (1 << 20)) return `${file.name} is ${sizeText(file.size)}; the limit is ${limitMb} MB.`;
  return null;
}

type Props = { paperId: string; initial: PaperFileOut[]; abstractOnly: boolean };

export function PaperFiles({ paperId, initial, abstractOnly }: Props) {
  const { user } = useAuth();
  const member = hasRole(user, "member");
  const files = usePaperFiles(paperId);
  const settings = useReviewSettings();
  const upload = useUploadPaperFile(paperId);
  const remove = useDeletePaperFile(paperId);
  const input = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<{ name: string; fraction: number } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const list = files.data ?? initial;
  const fulltext = settings.data?.current.fulltext;
  const enabled = fulltext ? fulltext.sources.includes("upload") : true;
  const limitMb = Math.min(fulltext?.upload_max_mb ?? 30, 30);

  const send = async (file: File | undefined) => {
    if (!file) return;
    setProblem(null);
    setMessage(null);
    const refused = checkFile(file, limitMb);
    if (refused) return setProblem(refused);
    setProgress({ name: file.name, fraction: 0 });
    try {
      const row = await upload.mutateAsync({ file, onProgress: (fraction) => setProgress({ name: file.name, fraction }) });
      setMessage(`Uploaded ${row.filename}. The next run that reviews this paper reads it.`);
    } catch (error) {
      setProblem(errorText(error));
    } finally {
      setProgress(null);
      if (input.current) input.current.value = "";
    }
  };
  const drop = (event: DragEvent) => {
    event.preventDefault();
    setOver(false);
    void send(event.dataTransfer.files[0]);
  };
  const del = async (file: PaperFileOut) => {
    if (!window.confirm(`Delete ${file.filename}? Runs that already used it keep their copy.`)) return;
    setProblem(null);
    setMessage(null);
    try {
      await remove.mutateAsync(file.id);
      setMessage(`Deleted ${file.filename}.`);
    } catch (error) {
      setProblem(errorText(error));
    }
  };

  return (
    <section className={`step step--${abstractOnly && list.length === 0 ? "warn" : "neutral"} paper-files`} aria-labelledby="files-heading">
      <h3 id="files-heading">{abstractOnly && list.length === 0 && member && enabled ? "Upload full text (PDF)" : "Full-text PDFs"}</h3>
      {abstractOnly && list.length === 0 && <p>Only the abstract was reviewed, so items it cannot answer count as not reported.{member && enabled ? " Upload the paper's PDF and the next run reviews the full text." : ""}</p>}
      {list.length > 0 && (
        <ul className="file-list">
          {list.map((file) => (
            <li key={file.id}>
              <span className="file-name">{file.filename}</span>
              <span className="sub">{sizeText(file.size)} · {file.uploaded_by_name ?? "unknown"} · {new Date(file.created_at).toLocaleDateString()}</span>
              <span className="file-actions">
                {member && <a href={`/api/v1/papers/${paperId}/files/${file.id}`} download={file.filename}>Download{" "}<span className="sr-only">{file.filename}</span></a>}
                {file.can_delete && <button type="button" onClick={() => void del(file)} disabled={remove.isPending}>Delete{" "}<span className="sr-only">{file.filename}</span></button>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {list.length === 0 && !abstractOnly && <p className="sub">No PDF uploaded for this paper.</p>}
      {member && enabled && (
        <div
          className={`dropzone ${over ? "is-over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop}
        >
          <input ref={input} type="file" accept="application/pdf,.pdf" className="sr-only" tabIndex={-1} aria-hidden="true" onChange={(e) => void send(e.target.files?.[0])} />
          <p>Drag a PDF here, or</p>
          <button type="button" onClick={() => input.current?.click()} disabled={!!progress}>Choose a PDF…</button>
          <p className="hint">PDF only, up to {limitMb} MB. Only open-access or your own copies: the text is sent to the AI providers.</p>
        </div>
      )}
      {member && !enabled && <p className="sub">Uploads are turned off in Settings → Full text.</p>}
      {progress && (
        <div className="upload-progress" role="status">
          <label>Uploading {progress.name}: {Math.round(progress.fraction * 100)}% <progress max={1} value={progress.fraction} /></label>
        </div>
      )}
      {problem && <p role="alert" className="form-error">{problem}</p>}
      {message && <p role="status" className="banner banner--ok">{message}</p>}
    </section>
  );
}
