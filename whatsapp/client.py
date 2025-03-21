import json
import logging
import requests
import os
from typing import Dict, Any, Optional, List

# Get environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Configure logging
logger = logging.getLogger(__name__)

class TelegramClient:
    """Client for interacting with the Telegram Bot API."""
    
    def __init__(self, bot_token=None):
        # Allow override via parameters or use environment values
        self.bot_token = bot_token or TELEGRAM_BOT_TOKEN
        
        # Validate credentials exist
        if not self.bot_token:
            logger.error("Telegram Bot token is missing")
            raise ValueError("Telegram Bot token is required")
            
        # Base URL for Telegram Bot API
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        
        logger.info("Telegram client initialized")
        # Log the first few characters of the bot token for debugging
        if self.bot_token:
            visible_part = self.bot_token[:5] + "..." + self.bot_token[-5:] if len(self.bot_token) > 10 else "***"
            logger.debug(f"Bot token format check: {visible_part} (length: {len(self.bot_token)})")
    
    def verify_credentials(self) -> bool:
        """
        Verify the bot token by making a test call to the Telegram Bot API.
        
        Returns:
            bool: True if credentials are valid, False otherwise
        """
        try:
            # Make a GET request to getMe endpoint to verify token
            verify_url = f"{self.base_url}/getMe"
            
            # Log the request for debugging
            logger.debug(f"Credential verification request: {verify_url}")
            
            response = requests.get(verify_url)
            
            # Log the response for debugging
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response body: {response.text}")
            
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    bot_info = result.get("result", {})
                    logger.info(f"Credentials verified for bot: {bot_info.get('username', 'Unknown')}")
                    return True
                else:
                    logger.error(f"API credential verification failed: {result.get('description')}")
                    return False
            else:
                logger.error(f"API credential verification failed: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error verifying API credentials: {e}")
            return False
    
    def send_message(self, chat_id: str, message: str, parse_mode: str = "Markdown") -> Dict[str, Any]:
        """
        Send a text message to a Telegram chat.
        
        Args:
            chat_id: The chat ID to send the message to
            message: The message text to send
            parse_mode: Message formatting mode (Markdown or HTML)
            
        Returns:
            The API response as a dictionary
        """
        url = f"{self.base_url}/sendMessage"
        
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": parse_mode
        }
        
        try:
            logger.debug(f"Sending message to {chat_id}: {message[:50]}...")
            
            # Log the request details for debugging
            logger.debug(f"Request payload: {json.dumps(payload)}")
            
            response = requests.post(url, json=payload)
            
            # Log the response for debugging
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response body: {response.text}")
            
            if response.status_code != 200:
                logger.error(f"Telegram API error: {response.status_code} - {response.text}")
                
                if response.status_code == 401:
                    logger.error("Authentication failed. Please check your Telegram Bot token.")
                
                return {
                    "error": True,
                    "status_code": response.status_code,
                    "message": response.text
                }
            
            result = response.json()
            if result.get("ok"):
                message_id = result.get("result", {}).get("message_id", "Unknown")
                logger.info(f"Message sent successfully. Message ID: {message_id}")
                return result
            else:
                logger.error(f"Telegram API error: {result.get('description')}")
                return {
                    "error": True,
                    "message": result.get('description')
                }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending Telegram message: {e}")
            return {"error": True, "message": str(e)}
    
    def send_button_message(self, chat_id: str, message: str, 
                           buttons: List[List[Dict[str, str]]], 
                           parse_mode: str = "Markdown") -> Dict[str, Any]:
        """
        Send a message with inline keyboard buttons.
        
        Args:
            chat_id: The chat ID to send the message to
            message: The message text to send
            buttons: List of button rows, each containing button objects
            parse_mode: Message formatting mode (Markdown or HTML)
            
        Returns:
            The API response as a dictionary
        """
        url = f"{self.base_url}/sendMessage"
        
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "reply_markup": {
                "inline_keyboard": buttons
            }
        }
        
        try:
            logger.debug(f"Sending button message to {chat_id}: {message[:50]}...")
            
            # Log the request details for debugging
            logger.debug(f"Request payload: {json.dumps(payload)}")
            
            response = requests.post(url, json=payload)
            
            # Log the response for debugging
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response body: {response.text}")
            
            if response.status_code != 200:
                logger.error(f"Telegram API error: {response.status_code} - {response.text}")
                return {
                    "error": True,
                    "status_code": response.status_code,
                    "message": response.text
                }
            
            result = response.json()
            if result.get("ok"):
                message_id = result.get("result", {}).get("message_id", "Unknown")
                logger.info(f"Button message sent successfully. Message ID: {message_id}")
                return result
            else:
                logger.error(f"Telegram API error: {result.get('description')}")
                return {
                    "error": True,
                    "message": result.get('description')
                }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending button message: {e}")
            return {"error": True, "message": str(e)}
    
    def parse_incoming_message(self, webhook_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse an incoming Telegram webhook payload.
        
        Args:
            webhook_payload: The webhook payload from Telegram
            
        Returns:
            Dictionary with sender_id, message_text, and timestamp if a valid message,
            None otherwise
        """
        try:
            logger.debug(f"Parsing webhook payload: {json.dumps(webhook_payload)[:200]}...")
            
            # Check if this is a callback query (button press)
            if "callback_query" in webhook_payload:
                callback_query = webhook_payload["callback_query"]
                return {
                    "sender_id": str(callback_query["from"]["id"]),
                    "message_id": callback_query["message"]["message_id"],
                    "message_type": "callback_query",
                    "message_text": callback_query["data"],
                    "timestamp": callback_query.get("message", {}).get("date")
                }
            
            # Regular message
            if "message" not in webhook_payload:
                logger.info("No message in webhook payload")
                return None
                
            message = webhook_payload["message"]
            
            # Check if it's a text message
            if "text" not in message:
                logger.info("Message contains no text")
                return None
                
            return {
                "sender_id": str(message["from"]["id"]),
                "message_id": message["message_id"],
                "message_type": "text",
                "message_text": message["text"],
                "timestamp": message.get("date")
            }
            
        except (KeyError, TypeError) as e:
            logger.error(f"Error parsing webhook: {e}")
            logger.debug(f"Problematic payload: {json.dumps(webhook_payload)}")
            return None