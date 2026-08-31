import { useEffect, useState } from 'react'
import { createNote, deleteNote, fetchNotes, updateNote } from '../lib/api'
import type { Note } from '../lib/api'
import { Card } from './ui/Card'
import { Skeleton } from './ui/Skeleton'

// 종목 메모. 국내·미국 상세 양쪽에 붙는다.
//
// 기획서가 이 기능을 "이 프로젝트의 차별점" 이라 불렀다 — 증권사 HTS 에는 없고, 흘려보내던
// 코멘트를 종목별로 쌓으면 시간이 지날수록 자산이 된다.
//
// 그래서 화면에서 지키는 것 셋:
//   1. **쓰기가 쉬워야 한다.** 접혀 있으면 안 쓰게 된다. 입력칸을 처음부터 펼쳐 둔다.
//   2. **언제 썼는지가 보여야 한다.** 판단의 시점이 메모의 값어치다. 고친 메모는 그 사실도 적는다.
//   3. **실수로 지워지지 않아야 한다.** 지우기는 한 번 더 눌러야 실행된다
//      (confirm 창은 쓰지 않는다 — 자동화 도구를 멈추게 하고, 흐름도 끊는다).

type Props = {
  symbol: string
}

const RECENT = 3

export function StockNotes({ symbol }: Props) {
  const [notes, setNotes] = useState<Note[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  const [draft, setDraft] = useState('')
  const [tags, setTags] = useState('')
  const [saving, setSaving] = useState(false)

  const load = () =>
    fetchNotes(symbol)
      .then(setNotes)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setNotes([])
    setDraft('')
    setTags('')
    setExpanded(false)

    fetchNotes(symbol)
      .then((r) => !cancelled && setNotes(r))
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false))

    return () => {
      cancelled = true
    }
  }, [symbol])

  const save = () => {
    const body = draft.trim()
    if (!body || saving) return
    setSaving(true)
    setError(null)
    createNote(symbol, body, splitTags(tags))
      .then(() => {
        setDraft('')
        setTags('')
        return load()
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setSaving(false))
  }

  const shown = expanded ? notes : notes.slice(0, RECENT)

  return (
    <Card
      title="메모"
      hint="이 종목에 대한 내 기록"
      meta={notes.length > 0 ? <span className="tabular">{notes.length}건</span> : undefined}
      bodyClassName=""
    >

      <div className="space-y-3 px-3 py-3">
        <div className="space-y-1.5">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            // Ctrl+Enter 로도 저장한다. 긴 글을 쓰다가 마우스로 옮겨 가지 않아도 되게.
            onKeyDown={(event) => {
              if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) save()
            }}
            rows={3}
            placeholder="지금 무슨 생각인지 적어 둔다. 나중에 이 판단이 맞았는지 보게 된다."
            className="w-full resize-y rounded-md border border-neutral-800 bg-neutral-900 px-2.5 py-2 text-sm placeholder:text-neutral-600 focus:border-neutral-600"
          />
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={tags}
              onChange={(event) => setTags(event.target.value)}
              placeholder="태그 (쉼표로 구분)"
              className="w-44 rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-xs placeholder:text-neutral-600 focus:border-neutral-600"
            />
            <button
              onClick={save}
              disabled={saving || draft.trim() === ''}
              className="rounded-md bg-neutral-100 px-3 py-1 text-xs text-neutral-900 transition-colors hover:bg-white disabled:opacity-40"
            >
              {saving ? '저장 중…' : '저장'}
            </button>
            <span className="text-[10px] text-neutral-600">Ctrl+Enter</span>
          </div>
        </div>

        {error && <p className="text-xs text-red-400">{error}</p>}
        {loading && <Skeleton rows={3} label="메모를 받는 중…" />}

        {!loading && notes.length === 0 && !error && (
          <p className="text-xs text-neutral-600">아직 메모가 없습니다.</p>
        )}

        {shown.length > 0 && (
          <ul className="divide-y divide-neutral-800/70 border-t border-neutral-800 pt-1">
            {shown.map((note) => (
              <NoteRow key={note.id} note={note} onChanged={load} />
            ))}
          </ul>
        )}

        {notes.length > RECENT && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-xs text-neutral-500 transition-colors hover:text-neutral-300"
          >
            {expanded ? '접기' : `이전 메모 ${notes.length - RECENT}건 더 보기`}
          </button>
        )}
      </div>
    </Card>
  )
}

function NoteRow({ note, onChanged }: { note: Note; onChanged: () => void }) {
  const [editing, setEditing] = useState(false)
  const [body, setBody] = useState(note.body)
  const [tags, setTags] = useState(note.tags.join(', '))
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

  const commit = () => {
    if (busy || body.trim() === '') return
    setBusy(true)
    updateNote(note.id, body.trim(), splitTags(tags))
      .then(() => {
        setEditing(false)
        onChanged()
      })
      .finally(() => setBusy(false))
  }

  const remove = () => {
    if (!confirming) {
      setConfirming(true)
      return
    }
    setBusy(true)
    deleteNote(note.id)
      .then(onChanged)
      .finally(() => setBusy(false))
  }

  if (editing) {
    return (
      <li className="space-y-1.5 py-2">
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          rows={3}
          className="w-full resize-y rounded-md border border-neutral-700 bg-neutral-900 px-2.5 py-2 text-sm focus:border-neutral-500"
        />
        <input
          value={tags}
          onChange={(event) => setTags(event.target.value)}
          placeholder="태그 (쉼표로 구분)"
          className="w-44 rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-xs placeholder:text-neutral-600"
        />
        <div className="flex gap-2 text-xs">
          <button onClick={commit} disabled={busy} className="text-neutral-200 hover:text-white">
            저장
          </button>
          <button
            onClick={() => {
              setEditing(false)
              setBody(note.body)
              setTags(note.tags.join(', '))
            }}
            className="text-neutral-500 hover:text-neutral-300"
          >
            취소
          </button>
        </div>
      </li>
    )
  }

  return (
    <li className="group py-2">
      {/* 줄바꿈을 그대로 살린다. 메모는 문단으로 쓰는 글이다. */}
      <p className="whitespace-pre-wrap text-sm text-neutral-200">{note.body}</p>

      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-neutral-600">
        <span className="tabular">{formatNoteTime(note.created_at)}</span>
        {note.edited && <span title={formatNoteTime(note.updated_at)}>수정됨</span>}
        {note.tags.map((tag) => (
          <span key={tag} className="rounded bg-neutral-800 px-1.5 py-0.5 text-neutral-400">
            #{tag}
          </span>
        ))}
        <span className="ml-auto flex gap-2 opacity-0 transition-opacity group-hover:opacity-100">
          <button onClick={() => setEditing(true)} className="hover:text-neutral-300">
            고치기
          </button>
          {/* 한 번 더 눌러야 지워진다. confirm 창은 쓰지 않는다. */}
          <button
            onClick={remove}
            disabled={busy}
            className={confirming ? 'text-red-400' : 'hover:text-neutral-300'}
          >
            {confirming ? '정말 지울까요?' : '지우기'}
          </button>
        </span>
      </div>
    </li>
  )
}

function splitTags(raw: string): string[] {
  return raw
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean)
}

/** 2026-08-20T04:50:00+00:00 → 8/20 (목) 13:50 */
function formatNoteTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const weekday = ['일', '월', '화', '수', '목', '금', '토'][date.getDay()]
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getMonth() + 1}/${date.getDate()} (${weekday}) ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
