import { ReactNode } from 'react'
import { SxProps, TableRow, TableRowProps, Theme } from '@mui/material'

import { useLongPress } from '../../hooks/useLongPress'

interface LongPressTableRowProps<T> extends Omit<TableRowProps, 'children'> {
  payload: T
  onLongPress: (payload: T) => void
  children: ReactNode
  enableLongPress?: boolean
  rowSx?: SxProps<Theme>
}

export default function LongPressTableRow<T>({
  payload,
  onLongPress,
  children,
  enableLongPress = true,
  rowSx,
  ...props
}: LongPressTableRowProps<T>) {
  const handlers = useLongPress(onLongPress, payload)

  return (
    <TableRow
      {...props}
      {...(enableLongPress ? handlers : {})}
      sx={rowSx}
    >
      {children}
    </TableRow>
  )
}
