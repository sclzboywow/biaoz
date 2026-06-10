import { reactive } from 'vue'

export type CursorPager = {
  page: number
  cursors: Array<number | null>
  nextCursor?: number | null
  hasMore: boolean
}

export function createCursorPager() {
  return reactive<CursorPager>({ page: 1, cursors: [null], nextCursor: null, hasMore: false })
}

export function resetCursorPager(pager: CursorPager) {
  pager.page = 1
  pager.cursors = [null]
  pager.nextCursor = null
  pager.hasMore = false
}

export function applyPageResult(pager: CursorPager, page: { next_cursor?: number | null; has_more?: boolean }) {
  pager.nextCursor = page.next_cursor ?? null
  pager.hasMore = Boolean(page.has_more)
}

export function pageParams<T extends { page: number }>(query: T, pager: CursorPager) {
  const { page: _page, ...params } = query
  const cursor = pager.cursors[pager.page - 1]
  return { ...params, cursor: cursor ?? undefined }
}

export function applyPageResultWithQuery<T extends { page: number }>(
  query: T,
  pager: CursorPager,
  page: { next_cursor?: number | null; has_more?: boolean },
) {
  query.page = pager.page
  applyPageResult(pager, page)
}

export async function nextCursorPage(pager: CursorPager, loader: () => Promise<void>) {
  if (!pager.hasMore || !pager.nextCursor) return
  pager.cursors[pager.page] = pager.nextCursor
  pager.page += 1
  await loader()
}

export async function prevCursorPage(pager: CursorPager, loader: () => Promise<void>) {
  if (pager.page <= 1) return
  pager.page -= 1
  await loader()
}
