# services/notes.py

from datetime import datetime
from typing import Dict, Any, List, Optional, BinaryIO
import logging
import base64
import os
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from database import crud
from database.models import NoteType
from llm.processor import LLMProcessor

logger = logging.getLogger(__name__)

class NotesService:
    """Service for managing user notes with multimodal support and Notion integration."""
    
    def __init__(self, db: Session):
        self.db = db
        self.llm_processor = LLMProcessor()
        self.local_media_path = os.environ.get("MEDIA_STORAGE_PATH", "./media")
        
        # Ensure media directory exists
        os.makedirs(self.local_media_path, exist_ok=True)
    
    async def create_note(self, user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new note for the user with optional multimodal content.
        
        Args:
            user_id: User ID
            data: Dictionary with note details:
                - title: Note title
                - content: Text content
                - tags: Optional list of tags
                - media: Optional list of media items (base64 encoded)
                - media_types: Optional list of media types matching media items
                
        Returns:
            Dict with status and note details
        """
        title = data.get("title", "Untitled Note")
        content = data.get("content", "")
        tags = data.get("tags", [])
        media_items = data.get("media", [])
        media_types = data.get("media_types", [])
        
        # Determine note type based on content
        note_type = NoteType.TEXT
        if media_items:
            if len(media_items) == 1:
                if media_types[0].startswith("image/"):
                    note_type = NoteType.IMAGE
                elif media_types[0].startswith("audio/"):
                    note_type = NoteType.AUDIO
                elif media_types[0].startswith("video/"):
                    note_type = NoteType.VIDEO
            else:
                note_type = NoteType.MIXED
        
        # Create note in database
        note = crud.create_note(
            db=self.db,
            user_id=user_id,
            title=title,
            content=content,
            note_type=note_type,
            tags=",".join(tags) if tags else ""
        )
        
        # Process and save any media attachments
        media_paths = []
        if media_items and len(media_items) == len(media_types):
            for i, (media_data, media_type) in enumerate(zip(media_items, media_types)):
                try:
                    # Generate filename based on note id and media index
                    extension = self._get_file_extension(media_type)
                    filename = f"{note.id}_{i}{extension}"
                    filepath = os.path.join(self.local_media_path, filename)
                    
                    # Decode and save media file
                    media_binary = base64.b64decode(media_data)
                    with open(filepath, "wb") as f:
                        f.write(media_binary)
                    
                    # Create media attachment record
                    media_paths.append(filepath)
                    crud.create_media_attachment(
                        db=self.db,
                        note_id=note.id,
                        media_type=media_type,
                        filepath=filepath
                    )
                except Exception as e:
                    logger.error(f"Error saving media for note {note.id}: {e}")
        
        # Sync with Notion if user has Notion connected
        notion_result = {"synced": False}
        user = crud.get_user_by_id(self.db, user_id)
        if user and user.notion_access_token and user.notion_notes_db_id:
            try:
                from services.notion import NotionService
                notion_service = NotionService(self.db)
                
                # Format the note for Notion
                entry_data = {
                    "Name": title,
                    "Content Snippet": content[:100] + ("..." if len(content) > 100 else ""),
                    "Tags": ", ".join(tags) if tags else ""
                }
                
                # Add entry to Notion Notes database
                notion_result = await notion_service.add_entry_to_database(
                    user_id=user_id,
                    database_id=user.notion_notes_db_id,
                    entry_data=entry_data
                )
                
                # Update local note with Notion page URL if successful
                if notion_result.get("status") == "success" and notion_result.get("page_url"):
                    crud.update_note_notion_url(
                        db=self.db,
                        note_id=note.id,
                        notion_url=notion_result.get("page_url")
                    )
                    notion_result["synced"] = True
            except Exception as e:
                logger.error(f"Error syncing note {note.id} to Notion: {e}")
                notion_result = {"synced": False, "error": str(e)}
        
        return {
            "status": "success",
            "note_id": note.id,
            "title": title,
            "content": content,
            "created_at": note.created_at.isoformat(),
            "note_type": note_type.value,
            "tags": tags,
            "media_count": len(media_paths),
            "notion_sync": notion_result
        }
    
    def get_notes(self, user_id: int, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Get notes for the user with optional filtering.
        
        Args:
            user_id: User ID
            filters: Dictionary with filter options:
                - tags: List of tags to filter by
                - search: Text to search in title/content
                - date_from: Start date
                - date_to: End date
                - note_type: Type of note
                
        Returns:
            List of notes as dictionaries
        """
        if filters is None:
            filters = {}
        
        # Extract filter parameters
        tags = filters.get("tags", [])
        search_text = filters.get("search", "")
        date_from = filters.get("date_from")
        date_to = filters.get("date_to")
        note_type = filters.get("note_type")
        
        # Apply filters
        notes = crud.get_notes(
            db=self.db,
            user_id=user_id,
            tags=tags,
            search_text=search_text,
            date_from=date_from,
            date_to=date_to,
            note_type=note_type
        )
        
        # Format results
        result = []
        for note in notes:
            # Get media attachments
            attachments = crud.get_media_attachments(db=self.db, note_id=note.id)
            
            note_tags = note.tags.split(",") if note.tags else []
            result.append({
                "id": note.id,
                "title": note.title,
                "content": note.content,
                "created_at": note.created_at.isoformat(),
                "updated_at": note.updated_at.isoformat() if note.updated_at else None,
                "note_type": note.note_type.value,
                "tags": note_tags,
                "media_attachments": [
                    {"type": a.media_type, "filepath": a.filepath} for a in attachments
                ],
                "notion_url": note.notion_url
            })
        
        return result
    
    def get_note_by_id(self, user_id: int, note_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific note by ID.
        
        Args:
            user_id: User ID
            note_id: Note ID
            
        Returns:
            Note as dictionary if found, None otherwise
        """
        note = crud.get_note_by_id(db=self.db, note_id=note_id)
        
        if not note or note.user_id != user_id:
            return None
        
        # Get media attachments
        attachments = crud.get_media_attachments(db=self.db, note_id=note.id)
        
        note_tags = note.tags.split(",") if note.tags else []
        return {
            "id": note.id,
            "title": note.title,
            "content": note.content,
            "created_at": note.created_at.isoformat(),
            "updated_at": note.updated_at.isoformat() if note.updated_at else None,
            "note_type": note.note_type.value,
            "tags": note_tags,
            "media_attachments": [
                {"type": a.media_type, "filepath": a.filepath} for a in attachments
            ],
            "notion_url": note.notion_url
        }
    
    async def update_note(self, user_id: int, note_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing note.
        
        Args:
            user_id: User ID
            note_id: Note ID
            data: Dictionary with note details to update
                
        Returns:
            Dict with status and updated note details
        """
        # Check note exists and belongs to user
        note = crud.get_note_by_id(db=self.db, note_id=note_id)
        if not note or note.user_id != user_id:
            return {"status": "error", "message": "Note not found or access denied"}
        
        # Extract update data
        title = data.get("title")
        content = data.get("content")
        tags = data.get("tags")
        
        # Update note in database
        updated_note = crud.update_note(
            db=self.db,
            note_id=note_id,
            title=title,
            content=content,
            tags=",".join(tags) if tags else None
        )
        
        # Sync with Notion if note has a Notion URL
        notion_result = {"synced": False}
        if updated_note.notion_url:
            try:
                # Implementation for updating an existing Notion page would go here
                # This requires the Notion page ID, which we could extract from the URL
                # or store separately in the database
                
                # For now, we'll just log a message
                logger.info(f"Note {note_id} has Notion URL {updated_note.notion_url} but update not implemented yet")
                notion_result = {"synced": False, "message": "Notion update not implemented yet"}
            except Exception as e:
                logger.error(f"Error updating note {note_id} in Notion: {e}")
                notion_result = {"synced": False, "error": str(e)}
        
        note_tags = updated_note.tags.split(",") if updated_note.tags else []
        return {
            "status": "success",
            "note_id": updated_note.id,
            "title": updated_note.title,
            "content": updated_note.content,
            "updated_at": updated_note.updated_at.isoformat() if updated_note.updated_at else None,
            "tags": note_tags,
            "notion_sync": notion_result
        }
    
    async def delete_note(self, user_id: int, note_id: int) -> Dict[str, Any]:
        """
        Delete a note and its associated media.
        
        Args:
            user_id: User ID
            note_id: Note ID
                
        Returns:
            Dict with status and message
        """
        # Check note exists and belongs to user
        note = crud.get_note_by_id(db=self.db, note_id=note_id)
        if not note or note.user_id != user_id:
            return {"status": "error", "message": "Note not found or access denied"}
        
        # Get media attachments before deleting
        attachments = crud.get_media_attachments(db=self.db, note_id=note_id)
        
        # Delete note (should cascade delete media attachments in DB)
        success = crud.delete_note(db=self.db, note_id=note_id)
        
        if success:
            # Delete media files from storage
            for attachment in attachments:
                try:
                    if os.path.exists(attachment.filepath):
                        os.remove(attachment.filepath)
                except Exception as e:
                    logger.error(f"Error deleting media file {attachment.filepath}: {e}")
            
            # If note has a Notion URL, we could potentially delete it from Notion as well
            # This would require implementing a delete method in NotionService
            
            return {
                "status": "success",
                "message": f"Note '{note.title}' has been deleted."
            }
        else:
            return {
                "status": "error",
                "message": f"Failed to delete note '{note.title}'."
            }
    
    async def create_notion_note(self, user_id: int, title: str, content: str, parent_page_id: str) -> Dict[str, Any]:
        """
        Create a note directly in Notion.
        
        Args:
            user_id: User ID
            title: Note title
            content: Note content
            parent_page_id: Parent page ID in Notion
                
        Returns:
            Dict with status and note details
        """
        try:
            from services.notion import NotionService
            notion_service = NotionService(self.db)
            result = await notion_service.create_note_page(
                user_id=user_id,
                title=title,
                content=content,
                parent_page_id=parent_page_id
            )
            
            # If successful, also create a local note with the Notion URL
            if result.get("status") == "success" and result.get("page_url"):
                note = crud.create_note(
                    db=self.db,
                    user_id=user_id,
                    title=title,
                    content=content,
                    note_type=NoteType.TEXT,
                    tags="notion",
                    notion_url=result.get("page_url")
                )
                
                result["note_id"] = note.id
                
            return result
        except Exception as e:
            logger.error(f"Error creating note in Notion for user {user_id}: {e}")
            return {"status": "error", "message": f"Failed to create note in Notion: {str(e)}"}
    
    def _get_file_extension(self, mime_type: str) -> str:
        """
        Get file extension from MIME type.
        
        Args:
            mime_type: MIME type string
                
        Returns:
            File extension with dot
        """
        type_to_ext = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "audio/mpeg": ".mp3",
            "audio/wav": ".wav",
            "audio/ogg": ".ogg",
            "video/mp4": ".mp4",
            "video/webm": ".webm",
            "application/pdf": ".pdf"
        }
        
        return type_to_ext.get(mime_type.lower(), ".bin")