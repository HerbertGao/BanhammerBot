import re
from typing import Dict, List, Tuple
from telegram import Message
from config import Config
from utils.logger import logger

class SpamDetector:
    """垃圾消息检测器"""
    
    def __init__(self):
        self.config = Config.SPAM_DETECTION
    
    def detect_spam(self, message: Message) -> Tuple[bool, str, Dict]:
        """
        检测消息是否为垃圾消息
        
        Args:
            message: Telegram 消息对象
            
        Returns:
            (is_spam, reason, details): 是否为垃圾消息、原因、详细信息
        """
        details = {}
        
        # 检测GIF动画
        if message.animation:
            details['gif_detected'] = True
            return True, "包含GIF动画", details
        
        # 检测贴纸
        if message.sticker:
            details['sticker_detected'] = True
            return True, "包含贴纸", details
        
        # 只对文本消息进行其他检测
        if not message.text:
            return False, "", {}
        
        text = message.text
        
        # 检测禁止词汇
        forbidden_found = self._check_forbidden_words(text)
        if forbidden_found:
            details['forbidden_words'] = forbidden_found
            return True, f"包含禁止词汇: {', '.join(forbidden_found)}", details
        
        # 检测链接数量
        link_count = self._count_links(text)
        if link_count > self.config['max_links_per_message']:
            details['link_count'] = link_count
            return True, f"链接数量过多: {link_count}个", details
        
        # 检测大写字母比例
        caps_percentage = self._calculate_caps_percentage(text)
        if caps_percentage > self.config['max_caps_percentage']:
            details['caps_percentage'] = caps_percentage
            return True, f"大写字母比例过高: {caps_percentage}%", details
        
        # 检测重复字符
        repetitive_chars = self._check_repetitive_chars(text)
        if repetitive_chars:
            details['repetitive_chars'] = repetitive_chars
            return True, f"包含重复字符: {repetitive_chars}", details
        
        # 检测消息长度
        if len(text) < self.config['min_message_length']:
            details['message_length'] = len(text)
            return True, f"消息过短: {len(text)}字符", details
        
        return False, "", details
    
    def _check_forbidden_words(self, text: str) -> List[str]:
        """检查禁止词汇"""
        found_words = []
        text_lower = text.lower()
        
        for word in self.config['forbidden_words']:
            if word.lower() in text_lower:
                found_words.append(word)
        
        return found_words
    
    def _count_links(self, text: str) -> int:
        """统计链接数量"""
        # 匹配各种链接格式
        url_patterns = [
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
            r'www\.(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
            r't\.me/[a-zA-Z0-9_]+',
            r'@[a-zA-Z0-9_]+',
        ]
        
        total_links = 0
        for pattern in url_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            total_links += len(matches)
        
        return total_links
    
    def _calculate_caps_percentage(self, text: str) -> float:
        """计算大写字母比例"""
        if not text:
            return 0.0
        
        letters = [char for char in text if char.isalpha()]
        if not letters:
            return 0.0
        
        caps_count = sum(1 for char in letters if char.isupper())
        return (caps_count / len(letters)) * 100
    
    def _check_repetitive_chars(self, text: str) -> str:
        """检查重复字符"""
        for i in range(len(text) - self.config['max_repetitive_chars'] + 1):
            char = text[i]
            if char.isalnum():  # 只检查字母和数字
                count = 1
                for j in range(i + 1, len(text)):
                    if text[j] == char:
                        count += 1
                    else:
                        break
                
                if count > self.config['max_repetitive_chars']:
                    return char * count
        
        return "" 