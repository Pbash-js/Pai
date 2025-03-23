import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, Any

class TimeProcessor:
    """Process natural language time expressions into structured date and time formats."""
    
    def __init__(self):
        self.today = datetime.now()
    
    def parse_natural_time(self, text: str) -> Dict[str, Any]:
        """
        Parse natural language time expressions from text.
        
        Args:
            text: Natural language text containing time references
            
        Returns:
            Dictionary with extracted date, time, and recurrence information
        """
        result = {
            "date": None,
            "time": None,
            "recurrence": None
        }
        
        # Process date references
        result["date"] = self._extract_date(text)
        
        # Process time references
        result["time"] = self._extract_time(text)
        
        # Process recurrence patterns
        result["recurrence"] = self._extract_recurrence(text)
        
        return result
    
    def _extract_date(self, text: str) -> Optional[str]:
        """Extract date from natural language text and return in YYYY-MM-DD format."""
        text = text.lower()
        
        # Check for today, tomorrow, day after tomorrow
        if "today" in text:
            return self.today.strftime("%Y-%m-%d")
        
        if "tomorrow" in text:
            tomorrow = self.today + timedelta(days=1)
            return tomorrow.strftime("%Y-%m-%d")
        
        if "day after tomorrow" in text:
            day_after = self.today + timedelta(days=2)
            return day_after.strftime("%Y-%m-%d")
        
        # Check for specific days of the week
        days = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, 
                "friday": 4, "saturday": 5, "sunday": 6}
        
        for day, day_num in days.items():
            if day in text:
                # Find the next occurrence of this day
                today_weekday = self.today.weekday()
                days_until = (day_num - today_weekday) % 7
                
                # If "next" is mentioned, add 7 days
                if f"next {day}" in text:
                    days_until += 7
                
                # If days_until is 0, it means today - check if we meant next week
                if days_until == 0 and "next" not in text:
                    days_until = 7
                
                target_date = self.today + timedelta(days=days_until)
                return target_date.strftime("%Y-%m-%d")
        
        # Check for "next week", "in a week"
        if "next week" in text or "in a week" in text:
            next_week = self.today + timedelta(days=7)
            return next_week.strftime("%Y-%m-%d")
        
        # Check for "next month"
        if "next month" in text:
            # Simple approximation - add 30 days
            next_month = self.today + timedelta(days=30)
            return next_month.strftime("%Y-%m-%d")
        
        # Check for specific date patterns (MM/DD, MM-DD, etc.)
        date_patterns = [
            r'(\d{1,2})[/-](\d{1,2})',               # MM/DD or M/D
            r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})'   # MM/DD/YYYY
        ]
        
        for pattern in date_patterns:
            matches = re.findall(pattern, text)
            if matches:
                # Process the first match
                match = matches[0]
                if len(match) == 2:  # MM/DD format
                    month, day = int(match[0]), int(match[1])
                    year = self.today.year
                    # If the date has already passed this year, assume next year
                    if month < self.today.month or (month == self.today.month and day < self.today.day):
                        year += 1
                elif len(match) == 3:  # MM/DD/YYYY format
                    month, day = int(match[0]), int(match[1])
                    year = int(match[2])
                    # Handle 2-digit years
                    if year < 100:
                        year += 2000
                
                try:
                    # Validate date
                    date_obj = datetime(year, month, day)
                    return date_obj.strftime("%Y-%m-%d")
                except ValueError:
                    # Invalid date, continue to next pattern
                    continue
        
        return None
    
    def _extract_time(self, text: str) -> Optional[str]:
        """Extract time from natural language text and return in HH:MM format."""
        text = text.lower()
        
        # Check for specific times (e.g., "at 3pm", "9:30 am")
        time_patterns = [
            r'(\d{1,2}):(\d{2})\s*([ap]\.?m\.?)',  # 3:30 pm
            r'(\d{1,2})\s*([ap]\.?m\.?)',          # 3 pm
            r'(\d{1,2}):(\d{2})',                  # 15:30 (24-hour)
        ]
        
        for pattern in time_patterns:
            matches = re.findall(pattern, text)
            if matches:
                match = matches[0]
                
                if len(match) == 3:  # 3:30 pm format
                    hour, minute = int(match[0]), int(match[1])
                    am_pm = match[2].lower()
                    
                    # Convert to 24-hour format
                    if 'p' in am_pm and hour < 12:
                        hour += 12
                    elif 'a' in am_pm and hour == 12:
                        hour = 0
                
                elif len(match) == 2:
                    # Check if it's "3 pm" format
                    if match[1].lower().startswith('a') or match[1].lower().startswith('p'):
                        hour, minute = int(match[0]), 0
                        am_pm = match[1].lower()
                        
                        # Convert to 24-hour
                        if 'p' in am_pm and hour < 12:
                            hour += 12
                        elif 'a' in am_pm and hour == 12:
                            hour = 0
                    else:  # It's "15:30" format
                        hour, minute = int(match[0]), int(match[1])
                
                return f"{hour:02d}:{minute:02d}"
        
        # Check for common time expressions
        if "noon" in text:
            return "12:00"
        
        if "midnight" in text:
            return "00:00"
        
        if "morning" in text:
            return "09:00"  # Default morning time
        
        if "afternoon" in text:
            return "14:00"  # Default afternoon time
        
        if "evening" in text:
            return "18:00"  # Default evening time
        
        if "night" in text:
            return "20:00"  # Default night time
        
        return None
    
    def _extract_recurrence(self, text: str) -> Optional[str]:
        """Extract recurrence pattern from text."""
        text = text.lower()
        
        # Check for daily/weekly/monthly patterns
        if re.search(r'every\s+day|daily', text):
            return "daily"
        
        if re.search(r'every\s+week|weekly', text):
            return "weekly"
        
        if re.search(r'every\s+month|monthly', text):
            return "monthly"
        
        # Check for specific day recurrence
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", 
                "saturday", "sunday"]
        
        for day in days:
            if f"every {day}" in text:
                return f"weekly-{day}"
        
        # Check for "every X days/weeks/months"
        patterns = [
            (r'every\s+(\d+)\s+day', 'days'),
            (r'every\s+(\d+)\s+week', 'weeks'),
            (r'every\s+(\d+)\s+month', 'months')
        ]
        
        for pattern, unit in patterns:
            match = re.search(pattern, text)
            if match:
                count = match.group(1)
                return f"every-{count}-{unit}"
        
        return None