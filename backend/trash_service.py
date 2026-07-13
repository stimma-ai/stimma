"""Service for handling trash operations (soft delete, restore, permanent delete).

Simplified implementation: trashed files stay in place until trash is emptied.
The deleted_at timestamp marks items as trashed, files are only deleted when
emptying the trash.
"""

from pathlib import Path
import shutil


class TrashService:
    """Handles permanent deletion of files when emptying trash."""

    def permanently_delete(self, file_path: str) -> None:
        """
        Permanently delete a file and its sidecar files.

        Args:
            file_path: Path to the file to delete

        Missing files are already-deleted success. Other filesystem failures are
        propagated so the durable delete operation remains retryable.
        """
        file_path = Path(file_path)

        # Delete the editor sidecar first. If this fails, leave the primary file
        # in place so the operation can retry without orphaning sensitive editor
        # state behind an already-missing primary file.
        sidecar_path = Path(str(file_path) + '.stimmaedit.json')
        if sidecar_path.exists():
            sidecar_path.unlink()

        if file_path.is_dir() and not file_path.is_symlink():
            shutil.rmtree(file_path)
        elif file_path.exists() or file_path.is_symlink():
            file_path.unlink()
