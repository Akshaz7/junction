import { UPLOAD_ACCEPT, validateUpload } from './upload-state'

/** True when a drag carries files (not text, links or in-page elements). */
export function isFileDrag(transfer: Pick<DataTransfer, 'types'> | null | undefined): boolean {
  return !!transfer && Array.from(transfer.types ?? []).includes('Files')
}

/** Picks the single droppable file, or explains why not. Same rules as the upload dialog. */
export function pickDroppedFile(files: ArrayLike<File> | null | undefined): { file: File } | { error: string } | null {
  if (!files?.length) return null
  if (files.length !== 1) return { error: 'Drop one drawing at a time.' }
  const invalid = validateUpload(files[0])
  return invalid ? { error: invalid } : { file: files[0] }
}

export { UPLOAD_ACCEPT }
