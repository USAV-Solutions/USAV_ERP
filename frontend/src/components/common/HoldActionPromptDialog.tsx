import { ReactNode, useState } from 'react'
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
} from '@mui/material'

interface HoldActionPromptDialogProps {
  open: boolean
  title: string
  onClose: () => void
  onSave: () => void
  onDelete: () => void
  saveDisabled?: boolean
  deleteDisabled?: boolean
  saveLoading?: boolean
  deleteLoading?: boolean
  deleteConfirmTitle?: string
  deleteConfirmMessage: ReactNode
  children: ReactNode
}

export default function HoldActionPromptDialog({
  open,
  title,
  onClose,
  onSave,
  onDelete,
  saveDisabled = false,
  deleteDisabled = false,
  saveLoading = false,
  deleteLoading = false,
  deleteConfirmTitle = 'Are you sure?',
  deleteConfirmMessage,
  children,
}: HoldActionPromptDialogProps) {
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false)

  const handleDelete = () => {
    setConfirmDeleteOpen(false)
    onDelete()
  }

  return (
    <>
      <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
        <DialogTitle>{title}</DialogTitle>
        <DialogContent>{children}</DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            color="error"
            variant="outlined"
            onClick={() => setConfirmDeleteOpen(true)}
            disabled={deleteDisabled || deleteLoading}
          >
            {deleteLoading ? 'Deleting...' : 'Delete'}
          </Button>
          <Button
            variant="contained"
            onClick={onSave}
            disabled={saveDisabled || saveLoading}
          >
            {saveLoading ? 'Saving...' : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>{deleteConfirmTitle}</DialogTitle>
        <DialogContent>
          {typeof deleteConfirmMessage === 'string' ? (
            <Typography>{deleteConfirmMessage}</Typography>
          ) : (
            deleteConfirmMessage
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmDeleteOpen(false)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={handleDelete} disabled={deleteLoading}>
            {deleteLoading ? 'Deleting...' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
