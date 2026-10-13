"use client";

import { useEffect, useState } from "react";

import NodeSelect from "@/components/NodeSelect";
import {
  acq,
  errorMessage,
  type ImportedJob,
  type ImportRead,
  type ImportStatus,
  type Node,
  type PastJob,
} from "@/lib/api";
import { isInternal, track } from "@/lib/track";
import { prepareUpload, UploadError } from "@/lib/upload";

/* Resume / capture import (docs/10). Before login the read only fills the input form; the person
   checks it and sees the preview, and the login keeps it. A member ticks which jobs to add. The
   files are never stored. */

// Versions of the two notices below; the server refuses any other (change both together).
export const IMPORT_CONSENT_VERSION = "career_import_v1";
export const IMPORT_STATS_CONSENT_VERSION = "career_import_stats_v1";
const isPdf = (f: File) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf");

const two = (m: number | null) => (m ? `.${String(m).padStart(2, "0")}` : "");
export function period(x: Pick<ImportedJob, "start_year" | "start_month" | "end_year" | "end_month" | "is_current">) {
  if (!x.start_year) return "시작 연도 모름";
  const end = x.is_current ? "현재" : x.end_year ? `${x.end_year}${two(x.end_month)}` : "";
  return `${x.start_year}${two(x.start_month)} – ${end}`;
}

/** A read experience as a past job (null: no start year, so it cannot be placed in time). */
export function toPastJob(x: ImportedJob, role: string): PastJob | null {
  if (!x.start_year || !(role || x.title)) return null;
  return {
    organization_id: x.suggested_organization_id, organization_name: x.company,
    role_node_id: role || null, role_raw: x.title, start_year: x.start_year, start_month: x.start_month,
    end_year: x.is_current ? null : x.end_year, end_month: x.is_current ? null : x.end_month,
    employment_type: x.employment_type, is_current: x.is_current,
  };
}

export function ImportUpload({ member, onRead, onManual }: {
  member: boolean; onRead: (r: ImportRead) => void; onManual: () => void;
}) {
  const [status, setStatus] = useState<ImportStatus | null>();
  const [files, setFiles] = useState<File[]>([]);
  const [agree, setAgree] = useState(false);
  const [stats, setStats] = useState(false); // optional: keep what is read for anonymous statistics
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  useEffect(() => {
    track("import_viewed", { member });
    acq.importStatus().then(setStatus).catch(() => setStatus(null));
  }, [member]);
  const max = status?.max_files ?? 4;
  const add = (list: FileList | null) => {
    // Copied now: the input is cleared right after, and a FileList is live.
    const picked = Array.from(list ?? []);
    if (!picked.length) return;
    setErr(undefined);
    setFiles((prev) => [...prev, ...picked].slice(0, max));
  };
  const read = async () => {
    setErr(undefined);
    setBusy(true);
    try {
      const parts = await prepareUpload(files);
      track("import_uploaded", { member, files: files.length, parts: parts.length, pdf: files.filter(isPdf).length,
                                 stats_consent: stats });
      const r = await acq.importParse(parts, IMPORT_CONSENT_VERSION, stats ? IMPORT_STATS_CONSENT_VERSION : null,
                                      isInternal());
      track("import_parsed", {
        member, source_kind: r.source_kind, experiences: r.experiences.length, education: r.education.length,
        roles_matched: r.experiences.filter((x) => x.suggested_role_node_id).length,
      });
      onRead(r);
    } catch (e) {
      setErr(e instanceof UploadError ? e.message
        : errorMessage(e) ?? "파일을 읽지 못했어요. 잠시 후 다시 시도하거나 직접 입력해 주세요.");
    } finally {
      setBusy(false);
    }
  };
  const unavailable = status === null || (status && !status.enabled);
  const usedUp = status?.enabled && status.remaining_today === 0;

  return (
    <section className="screen" aria-busy={busy}>
      <h2>{member ? "이력서·캡처로 경력 채우기" : "이력서·링*드인 캡처로 시작하기"}</h2>
      <p className="sub">기존 만들어둔 이력서, 링*드인 캡처 등을 올리시면 됩니다.</p>
      <ul className="import-points">
        <li>{member ? "경력만 읽어서 보여드려요. 더할 것만 고르면 돼요" : "경력·학력만 읽어서 입력칸을 채워요. 확인하고 고칠 수 있어요"}</li>
        <li>이름·연락처·사진은 읽지 않고, 파일은 저장하지 않아요</li>
      </ul>
      {unavailable || usedUp ? (
        <>
          <p className="hint">{usedUp ? "오늘은 파일 읽기를 더 할 수 없어요." : "지금은 파일 읽기를 쓸 수 없어요."} 직접 입력해도 같은 결과를 볼 수 있어요.</p>
          <button className="cta" onClick={onManual}>직접 입력할게요</button>
        </>
      ) : (
        <>
          <label className="dropzone">
            <input type="file" accept="application/pdf,image/*" multiple hidden disabled={busy}
                   onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
            <b>{files.length ? "파일 더 고르기" : "파일 고르기"}</b>
            <span>PDF 이력서 · 링*드인 캡처 이미지 · 최대 {max}개</span>
          </label>
          {files.length > 0 && (
            <ul className="filelist">
              {files.map((f, i) => (
                <li key={`${f.name}-${i}`}>
                  <span>{f.name}</span>
                  <button className="link" disabled={busy} aria-label={`${f.name} 빼기`}
                          onClick={() => setFiles(files.filter((_, j) => j !== i))}>빼기</button>
                </li>
              ))}
            </ul>
          )}
          <label className="check consent-all">
            <input type="checkbox" checked={agree && stats}
                   onChange={(e) => { setAgree(e.target.checked); setStats(e.target.checked); }} />
            <b>모두 동의하기</b>
          </label>
          <label className="check consent-detail">
            <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
            <span>
              <b>[필수] 파일 읽기를 위한 개인정보 국외 이전 동의</b><br />
              올린 파일을 읽기 위해 미국의 Anthropic(AI 서비스)에 보내요. 읽은 뒤 파일은 저장하지 않아요.
            </span>
          </label>
          <details className="consent-more">
            <summary>자세히 보기</summary>
            <ul>
              <li>이전받는 자: Anthropic, PBC (미국) · privacy@anthropic.com</li>
              <li>이전 일시·방법: 파일을 올릴 때, 암호화된 통신으로 전송</li>
              <li>이전 항목: 올린 파일에 담긴 내용 (이력서·캡처)</li>
              <li>이용 목적: 경력·학력 항목을 읽어 입력칸 채우기</li>
              <li>보유 기간: nextpath는 파일을 저장하지 않아요. Anthropic은 이 내용을 AI 학습에 쓰지 않고, 정해진 보관 기간이 지나면 지워요.</li>
              <li>동의하지 않아도 돼요. 동의하지 않으면 직접 입력으로 같은 결과를 볼 수 있어요.</li>
              <li><a href="/privacy" target="_blank" rel="noreferrer">개인정보처리방침 전문</a></li>
            </ul>
          </details>
          <label className="check consent-detail">
            <input type="checkbox" checked={stats} onChange={(e) => setStats(e.target.checked)} />
            <span>
              <b>[선택] 읽은 경력·학력을 익명 통계에 쓰는 것에 동의</b><br />
              가입하지 않아도, 읽은 회사·직무·학교·기간을 이름·연락처 없이 남겨
              &lsquo;나와 같은 자리였던 사람들&rsquo; 통계를 만드는 데 써요.
              보유 기간: 3년. 동의하지 않아도 파일 읽기는 그대로 돼요.
            </span>
          </label>
          {err && <p className="error" role="alert">{err}</p>}
          <button className="cta" disabled={busy || !files.length || !agree} onClick={() => void read()}>
            {busy ? "읽는 중이에요… (20초쯤 걸려요)" : "올리고 채우기"}
          </button>
          <button className="cta ghost" disabled={busy} onClick={onManual}>직접 입력할게요</button>
        </>
      )}
    </section>
  );
}

type Row = { x: ImportedJob; keep: boolean; role: string };

/** Rows for the jobs read from a file: pre-ticked unless already on record or not placeable. */
export function importRows(read: ImportRead, roles: Node[], skip: ImportedJob[] = []): Row[] {
  const listed = new Set(roles.map((r) => r.node_id));
  return read.experiences.filter((x) => !skip.includes(x)).map((x) => ({
    x, keep: Boolean(x.start_year) && !x.already_saved && !x.is_career_break,
    role: x.suggested_role_node_id && listed.has(x.suggested_role_node_id) ? x.suggested_role_node_id : "",
  }));
}

/** The read jobs as a list: tick to keep, pick a role if you like (the title stays as written). */
export function ImportedJobs({ rows, roles, onChange }: {
  rows: Row[]; roles: Node[]; onChange: (rows: Row[]) => void;
}) {
  const set = (i: number, patch: Partial<Row>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <ul className="imported">
      {rows.map((r, i) => (
        <li key={i} className={r.keep ? "" : "off"}>
          <label className="check">
            <input type="checkbox" checked={r.keep} disabled={!r.x.start_year || r.x.is_career_break}
                   onChange={(e) => set(i, { keep: e.target.checked })} />
            <span>
              <b>{r.x.company ?? "회사 이름 없음"}</b>{r.x.title ? ` · ${r.x.title}` : ""}
              {r.x.employment_type === "INTERN" && <em className="tag">인턴</em>}
              {r.x.already_saved && <em className="tag">이미 있어요</em>}
              {r.x.is_career_break && <em className="tag">경력 공백 · 저장하지 않아요</em>}
              <br /><small>{period(r.x)}</small>
            </span>
          </label>
          {r.keep && !r.x.is_career_break && (
            <NodeSelect nodes={roles} value={r.role} empty="직무 고르기 (선택)" ariaLabel="직무"
                        onChange={(v) => set(i, { role: v })} />
          )}
        </li>
      ))}
    </ul>
  );
}

/** A member: the jobs read from their file, ticked ones added to their profile. */
export function ImportReview({ read, roles, onDone }: {
  read: ImportRead; roles: Node[]; onDone: (added: number) => void;
}) {
  const [rows, setRows] = useState(() => importRows(read, roles));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  const jobs = rows.filter((r) => r.keep).map((r) => toPastJob(r.x, r.role)).filter((j): j is PastJob => j !== null);
  const save = async () => {
    setErr(undefined);
    setBusy(true);
    try {
      const r = await acq.importConfirm(read.import_attempt_id, jobs);
      track("import_confirmed", { member: true, added: r.added, skipped: r.skipped });
      onDone(r.added);
    } catch (e) {
      setErr(errorMessage(e) ?? "저장하지 못했어요. 잠시 후 다시 시도해 주세요.");
      setBusy(false);
    }
  };
  return (
    <section className="screen">
      <h2>읽은 경력이에요</h2>
      <p className="sub">더할 경력만 남겨 주세요. 직무는 읽은 내용으로 골라뒀어요. 다르면 바꿔 주세요.</p>
      {rows.length ? <ImportedJobs rows={rows} roles={roles} onChange={setRows} />
        : <p className="hint">경력을 찾지 못했어요. 다른 파일로 다시 올려 주세요.</p>}
      {err && <p className="error" role="alert">{err}</p>}
      <button className="cta" disabled={busy || !jobs.length} onClick={() => void save()}>
        {jobs.length ? `경력 ${jobs.length}개 더하기` : "더할 경력을 골라 주세요"}
      </button>
    </section>
  );
}

/** For members on their result: why to fill in the rest of their career. */
export function ImportEntry({ onOpen }: { onOpen: () => void }) {
  return (
    <div className="import-entry">
      <b>경력을 다 채우면 더 많이 보여요</b>
      <ul>
        <li>나와 같은 경로를 걸은 사람들의 다음 걸음까지 비교해요</li>
        <li>한 걸음 먼저 간 사람 중 나에게 도움이 될 사람도 그 경력으로 찾아드릴게요 (준비 중)</li>
      </ul>
      <button className="cta ghost" onClick={onOpen}>이력서·캡처로 경력 채우기</button>
    </div>
  );
}
