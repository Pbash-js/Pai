import json
import logging
import requests
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class TelegramWebhookManager:
    """Manager for handling Telegram webhook registrations."""
    
    def __init__(self, bot_token=None):
        """
        Initialize the webhook manager.
        
        Args:
            bot_token: Telegram Bot API token
        """
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        
        # Validate required parameters
        if not self.bot_token:
            raise ValueError("Telegram Bot token is required")
            
        logger.info(f"TelegramWebhookManager initialized")
    
    def register_webhook(self, callback_url: str) -> Dict[str, Any]:
        """
        Register a webhook URL with the Telegram Bot API.
        
        Args:
            callback_url: The webhook callback URL (e.g., ngrok URL + '/webhook')
            
        Returns:
            The API response as a dictionary
        """
        # Telegram Bot API endpoint for webhook registration
        url = f"https://api.telegram.org/bot{self.bot_token}/setWebhook"
        
        # Webhook registration payload
        payload = {
            "url": callback_url,
            "drop_pending_updates": True
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        try:
            logger.info(f"Registering webhook at {callback_url}")
            logger.debug(f"Webhook registration payload: {json.dumps(payload)}")
            
            response = requests.post(
                url,
                headers=headers,
                json=payload
            )
            
            # Log response for debugging
            logger.debug(f"Webhook registration response: {response.status_code} - {response.text}")
            
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    logger.info(f"Webhook registered successfully")
                    return result
                else:
                    logger.error(f"Failed to register webhook: {result.get('description')}")
                    return {
                        "error": True,
                        "message": result.get('description')
                    }
            else:
                logger.error(f"Failed to register webhook: {response.status_code} - {response.text}")
                return {
                    "error": True,
                    "status_code": response.status_code,
                    "message": response.text
                }
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error registering webhook: {e}")
            return {"error": True, "message": str(e)}
    
    def get_webhook_info(self) -> Dict[str, Any]:
        """
        Get information about the current webhook.
        
        Returns:
            The API response as a dictionary
        """
        url = f"https://api.telegram.org/bot{self.bot_token}/getWebhookInfo"
        
        try:
            logger.info("Getting webhook info")
            
            response = requests.get(url)
            
            # Log response for debugging
            logger.debug(f"Webhook info response: {response.status_code} - {response.text}")
            
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    return result["result"]
                else:
                    logger.error(f"Failed to get webhook info: {result.get('description')}")
                    return {
                        "error": True,
                        "message": result.get('description')
                    }
            else:
                logger.error(f"Failed to get webhook info: {response.status_code} - {response.text}")
                return {
                    "error": True,
                    "status_code": response.status_code,
                    "message": response.text
                }
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting webhook info: {e}")
            return {"error": True, "message": str(e)}
    
    def delete_webhook(self) -> Dict[str, Any]:
        """
        Delete the current webhook.
        
        Returns:
            The API response as a dictionary
        """
        url = f"https://api.telegram.org/bot{self.bot_token}/deleteWebhook"
        
        try:
            logger.info("Deleting webhook")
            
            response = requests.get(url)
            
            # Log response for debugging
            logger.debug(f"Delete webhook response: {response.status_code} - {response.text}")
            
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    logger.info("Webhook deleted successfully")
                    return result
                else:
                    logger.error(f"Failed to delete webhook: {result.get('description')}")
                    return {
                        "error": True,
                        "message": result.get('description')
                    }
            else:
                logger.error(f"Failed to delete webhook: {response.status_code} - {response.text}")
                return {
                    "error": True,
                    "status_code": response.status_code,
                    "message": response.text
                }
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error deleting webhook: {e}")
            return {"error": True, "message": str(e)}