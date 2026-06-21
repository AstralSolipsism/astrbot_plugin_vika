"""
维格表空间模块

兼容原vika.py库的space模块
"""
from .space import Space
from .space_manager import SpaceManager


__all__ = [
    'Space',
    'SpaceManager'
]
