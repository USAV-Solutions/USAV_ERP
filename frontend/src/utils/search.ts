export type SearchableField = string | number | null | undefined

const WHITESPACE = /\s+/g
const SEPARATORS = /[-_/]+/g

export function normalizeSearchText(value: string): string {
  return value
    .toLowerCase()
    .replace(SEPARATORS, ' ')
    .replace(WHITESPACE, ' ')
    .trim()
}

export function tokenizeSearchQuery(query: string): string[] {
  const normalized = normalizeSearchText(query)
  if (!normalized) return []
  return normalized.split(' ').filter(Boolean)
}

export function compileSearchMatcher(query: string): (fields: SearchableField[]) => boolean {
  const tokens = tokenizeSearchQuery(query)
  if (tokens.length === 0) {
    return () => true
  }

  return (fields: SearchableField[]) => {
    const normalizedFields = fields
      .map((field) => normalizeSearchText(String(field ?? '')))
      .filter(Boolean)

    if (normalizedFields.length === 0) return false

    return tokens.every((token) => normalizedFields.some((field) => field.includes(token)))
  }
}
