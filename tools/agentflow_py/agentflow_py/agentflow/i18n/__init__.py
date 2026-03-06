"""
i18n 国际化支持模块
支持中文（zh）和英文（en）两种语言
使用方式：t("task.completed") 或 t_lang("en", "task.completed")
"""

from .i18n import (
    T,
    TLang,
    SetDefaultLang,
    GetDefaultLang,
    ToolDesc,
    NormalizeLanguage,
    LangZH,
    LangEN,
)

__all__ = [
    "T",
    "TLang", 
    "SetDefaultLang",
    "GetDefaultLang",
    "ToolDesc",
    "NormalizeLanguage",
    "LangZH",
    "LangEN",
]
