import { ChangeEvent, KeyboardEvent, useEffect, useMemo, useState } from 'react'
import { Box, Button, TablePagination, TextField, Typography } from '@mui/material'

interface TablePaginationWithPageJumpProps {
  count: number
  page: number
  rowsPerPage: number
  rowsPerPageOptions?: number[]
  onPageChange: (page: number) => void
  onRowsPerPageChange: (rowsPerPage: number) => void
}

export default function TablePaginationWithPageJump({
  count,
  page,
  rowsPerPage,
  rowsPerPageOptions = [10, 25, 50, 100],
  onPageChange,
  onRowsPerPageChange,
}: TablePaginationWithPageJumpProps) {
  const [pageInput, setPageInput] = useState(String(page + 1))

  useEffect(() => {
    setPageInput(String(page + 1))
  }, [page])

  const totalPages = useMemo(() => {
    const pages = Math.ceil(Math.max(count, 0) / rowsPerPage)
    return Math.max(pages, 1)
  }, [count, rowsPerPage])

  const jumpToPage = () => {
    const requested = parseInt(pageInput, 10)
    if (Number.isNaN(requested)) {
      setPageInput(String(page + 1))
      return
    }

    const clamped = Math.min(Math.max(requested, 1), totalPages)
    onPageChange(clamped - 1)
    setPageInput(String(clamped))
  }

  const handlePageInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    setPageInput(e.target.value)
  }

  const handlePageInputKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      jumpToPage()
    }
  }

  return (
    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
      <TablePagination
        component="div"
        rowsPerPageOptions={rowsPerPageOptions}
        count={count}
        page={page}
        rowsPerPage={rowsPerPage}
        onPageChange={(_event: unknown, nextPage: number) => onPageChange(nextPage)}
        onRowsPerPageChange={(e: ChangeEvent<HTMLInputElement>) =>
          onRowsPerPageChange(parseInt(e.target.value, 10))
        }
      />
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, pr: 2 }}>
        <Typography variant="body2" color="text.secondary">
          Page
        </Typography>
        <TextField
          size="small"
          type="number"
          value={pageInput}
          onChange={handlePageInputChange}
          onKeyDown={handlePageInputKeyDown}
          inputProps={{ min: 1, max: totalPages, style: { width: 80 } }}
        />
        <Typography variant="body2" color="text.secondary">
          / {totalPages}
        </Typography>
        <Button size="small" variant="outlined" onClick={jumpToPage}>
          Go
        </Button>
      </Box>
    </Box>
  )
}
