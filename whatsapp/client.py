import json
import logging
import requests
from typing import Dict, Any, Optional

from config import WHATSAPP_API_KEY, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_BUSINESS_ACCOUNT_ID

logger = logging.getLogger(__name__)

class WhatsAppClient:
    """Client for interacting with the WhatsApp Business API."""
    
    def __init__(self):
        self.api_key = WHATSAPP_API_KEY
        self.phone_number_id = WHATSAPP_PHONE_NUMBER_ID
        self.business_account_id = WHATSAPP_BUSINESS_ACCOUNT_ID
        self.base_url = f"https://graph.facebook.com/v22.0/563867096813763/messages "
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    def send_message(self, recipient_phone: str, message: str) -> Dict[str, Any]:
        """
        Send a text message to a WhatsApp user.
        
        Args:
            recipient_phone: The recipient's phone number in international format (e.g., "15551234567")
            message: The message text to send
            
        Returns:
            The API response as a dictionary
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_phone,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message
            }
        }
        
        try:
            response = requests.post(
                self.base_url,
                headers=self.headers,
                data=json.dumps(payload)
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending WhatsApp message: {e}")
            return {"error": str(e)}
    
    def parse_incoming_message(self, webhook_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse an incoming WhatsApp webhook payload.
        
        Args:
            webhook_payload: The webhook payload from Meta
            
        Returns:
            Dictionary with sender_id, message_text, and timestamp if a valid message,
            None otherwise
        """
        try:
            # Extract entry from webhook
            entry = webhook_payload.get("entry", [])[0]
            changes = entry.get("changes", [])[0]
            value = changes.get("value", {})
            
            # Get messages
            messages = value.get("messages", [])
            if not messages:
                return None
            
            message = messages[0]
            if message.get("type") != "text":
                # Only handle text messages for now
                return None
            
            return {
                "sender_id": message.get("from"),
                "message_text": message.get("text", {}).get("body", ""),
                "timestamp": message.get("timestamp")
            }
        except (IndexError, KeyError) as e:
            logger.error(f"Error parsing webhook: {e}")
            return None