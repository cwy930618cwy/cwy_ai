"""
i18n 核心逻辑
提供轻量级国际化支持，支持中文（zh）和英文（en）两种语言
"""

import threading
from typing import Dict, Optional, Any

from .translations_en import translationsEN
from .translations_zh import translationsZH


# 语言代码常量
LangZH = "zh"  # 中文（默认）
LangEN = "en"  # 英文


# 全局默认语言
_default_lang: str = LangZH
_lock = threading.RLock()


def SetDefaultLang(lang: str) -> None:
    """
    设置全局默认语言
    
    Args:
        lang: 语言代码，支持 "zh"/"chinese"（中文）或 "en"/"english"（英文）
    """
    global _default_lang
    with _lock:
        lang_lower = lang.lower()
        if lang_lower in ("en", "english"):
            _default_lang = LangEN
        else:
            _default_lang = LangZH


def GetDefaultLang() -> str:
    """
    获取全局默认语言
    
    Returns:
        当前默认语言代码
    """
    with _lock:
        return _default_lang


def T(key: str, *args: Any) -> str:
    """
    翻译函数（使用全局默认语言）
    
    Args:
        key: 翻译键，格式为 module.key，如 "task.completed"
        *args: 可选的格式化参数（使用 Python format 格式）
    
    Returns:
        翻译后的字符串
    """
    return TLang(GetDefaultLang(), key, *args)


def TLang(lang: str, key: str, *args: Any) -> str:
    """
    翻译函数（指定语言）
    
    Args:
        lang: 语言代码
        key: 翻译键，格式为 module.key
        *args: 可选的格式化参数
    
    Returns:
        翻译后的字符串
    """
    lang_lower = lang.lower()
    if lang_lower in ("en", "english"):
        dict_data: Dict[str, str] = translationsEN
    else:
        dict_data = translationsZH
    
    val = dict_data.get(key)
    if val is None:
        # 回退：先尝试中文，再返回 key 本身
        val = translationsZH.get(key)
        if val is None:
            return key
    
    if args:
        try:
            return val.format(*args)
        except (IndexError, KeyError):
            return val
    return val


def ToolDesc(lang: str, tool_name: str) -> str:
    """
    获取工具描述的多语言版本
    如果指定语言没有对应翻译，回退到中文
    
    Args:
        lang: 语言代码
        tool_name: 工具名称
    
    Returns:
        工具描述
    """
    key = f"tool.{tool_name}.description"
    return TLang(lang, key)


def NormalizeLanguage(lang: str) -> str:
    """
    规范化语言代码
    
    Args:
        lang: 原始语言代码（如 "en-US", "en-GB", "zh-CN" 等）
    
    Returns:
        规范化后的语言代码（"zh" 或 "en"）
    """
    lang_lower = lang.lower()
    if lang_lower in ("en", "en-us", "en-gb", "english"):
        return LangEN
    return LangZH
