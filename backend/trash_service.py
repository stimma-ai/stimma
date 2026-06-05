"""Service for handling trash operations (soft delete, restore, permanent delete).

Simplified implementation: trashed files stay in place until trash is emptied.
The deleted_at timestamp marks items as trashed, files are only deleted when
emptying the trash.
"""

from pathlib import Path


class TrashService:
    """Handles permanent deletion of files when emptying trash."""

    def permanently_delete(self, file_path: str) -> None:
        """
        Permanently delete a file and its sidecar files.

        Args:
            file_path: Path to the file to delete

        Raises:
            FileNotFoundError: If the file doesn't exist
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not file_path.is_file():
            raise ValueError(f"Not a file: {file_path}")

        # Delete the file
        file_path.unlink()

        # Also delete the editor sidecar file if it exists
        sidecar_path = Path(str(file_path) + '.stimmaedit.json')
        if sidecar_path.exists():
            try:
                sidecar_path.unlink()
            except Exception:
                # Silently ignore errors deleting the sidecar
                pass
