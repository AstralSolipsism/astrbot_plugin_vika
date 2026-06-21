"""
维格表附件管理器

兼容原vika.py库的AttachmentManager类
"""
from typing import Dict, Any, Optional, List, Union, Callable, Awaitable
import aiohttp
import os
from pathlib import Path
import asyncio
from urllib.parse import urljoin
from ..exceptions import ParameterException, AttachmentException
from ..utils import run_sync

# 常量：下载分块大小（64 KiB）
DOWNLOAD_CHUNK_SIZE = 64 * 1024
# 魔法数→常量，便于配置/维护
DEFAULT_MAX_UPLOAD_SIZE_BYTES = 1 * 1024 * 1024 * 1024


class Attachment:
    """附件对象"""
    
    def __init__(self, attachment_data: Dict[str, Any]):
        self._data = attachment_data
    
    @property
    def token(self) -> str:
        """附件token"""
        return self._data.get('token', '')
    
    @property
    def name(self) -> str:
        """附件名称"""
        return self._data.get('name', '')
    
    @property
    def size(self) -> int:
        """附件大小（字节）"""
        return self._data.get('size', 0)
    
    @property
    def mime_type(self) -> str:
        """MIME类型"""
        return self._data.get('mimeType', '')
    
    @property
    def url(self) -> str:
        """附件访问URL"""
        return self._data.get('url', '')
    
    @property
    def width(self) -> Optional[int]:
        """图片宽度（如果是图片）"""
        return self._data.get('width')
    
    @property
    def height(self) -> Optional[int]:
        """图片高度（如果是图片）"""
        return self._data.get('height')
    
    @property
    def preview(self) -> Optional[str]:
        """预览URL"""
        return self._data.get('preview')
    
    @property
    def raw_data(self) -> Dict[str, Any]:
        """原始数据"""
        return self._data
    
    def __str__(self) -> str:
        return f"Attachment({self.name}, {self.size} bytes)"
    
    def __repr__(self) -> str:
        return f"Attachment(name='{self.name}', size={self.size}, mime_type='{self.mime_type}')"


class AttachmentManager:
    """
    附件管理器，提供附件上传和下载功能
    
    兼容原vika.py库的AttachmentManager接口
    """
    
    def __init__(self, datasheet, status_callback: Optional[Callable[[str], Awaitable[None]]] = None):
        """
        初始化附件管理器
        
        Args:
            datasheet: 数据表实例
        """
        self._datasheet = datasheet
        self.status_callback = status_callback
    
    async def aupload(self, file_path: str) -> Attachment:
        """
        上传附件（异步）
        
        Args:
            file_path: 本地文件路径
            
        Returns:
            上传后的附件对象
            
        Raises:
            AttachmentException: 上传失败时
            ParameterException: 参数错误时
        """
        if not os.path.exists(file_path):
            raise ParameterException(f"File not found: {file_path}")
        
        file_size = os.path.getsize(file_path)
        if file_size > DEFAULT_MAX_UPLOAD_SIZE_BYTES:  # 1GB limit
            raise AttachmentException("File size exceeds 1GB limit")
        
        response = await self._aupload_file(file_path, status_callback=self.status_callback)
        
        if response.get('success'):
            attachment_data = response.get('data', {})
            return Attachment(attachment_data)
        else:
            error_msg = response.get('message', 'Upload failed')
            raise AttachmentException(f"Failed to upload attachment: {error_msg}")
    
    async def aupload_file(self, file_path: str) -> Attachment:
        """
        上传文件（异步，原库兼容方法）
        
        Args:
            file_path: 本地文件路径
            
        Returns:
            上传后的附件对象
        """
        return await self.aupload(file_path)
    
    async def adownload(
        self,
        attachment: Union[Attachment, str, Dict[str, Any]],
        save_path: Optional[str] = None
    ) -> str:
        """
        下载附件（异步）
        
        Args:
            attachment: 附件对象、URL或附件数据字典
            save_path: 保存路径，如不指定则使用附件名称
            
        Returns:
            下载文件的本地路径
            
        Raises:
            AttachmentException: 下载失败时
        """
        # 获取下载URL和文件名
        if isinstance(attachment, Attachment):
            url = attachment.url
            filename = attachment.name
        elif isinstance(attachment, str):
            url = attachment
            filename = Path(attachment).name
        elif isinstance(attachment, dict):
            url = attachment.get('url', '')
            filename = attachment.get('name', 'attachment')
        else:
            raise ParameterException("Invalid attachment parameter")
        
        if not url:
            raise AttachmentException("No download URL available")
        
        # 规范化与越界校验：
        # - 若仅文件名语义，则强制剥离路径分隔符（Path(name).name）
        # - 若为目录+文件名语义，使用 resolve 后校验目标在基目录内，越界则抛出 ParameterException
        # 如此避免路径遍历写出到允许目录之外
        # 确定保存路径
        if save_path:
            sp = Path(save_path)
            # 目录语义判定：存在目录或字符串末尾带分隔符，则视为目录
            is_dir_semantics = sp.is_dir() or str(save_path).endswith(('/', '\\'))
            try:
                if is_dir_semantics:
                    base_dir = sp
                    target_name = Path(filename).name  # 去除任何分隔符
                else:
                    # 文件路径语义：目录为父级，文件名来自 save_path 自身（剥离分隔符）
                    base_dir = Path.cwd() if sp.parent == Path(".") else sp.parent
                    target_name = Path(sp.name).name
                base_dir_resolved = base_dir.resolve()
                target_path = (base_dir_resolved / target_name).resolve()
            except Exception as e:
                raise ParameterException(f"Invalid save_path: {save_path}") from e
            # 使用 os.path.commonpath() 进行更严格的路径验证，防止路径遍历攻击
            # 这种方法能正确处理符号链接、相对路径等边缘情况
            try:
                common = os.path.commonpath([str(base_dir_resolved), str(target_path)])
                if common != str(base_dir_resolved):
                    raise ParameterException("Target path escapes base directory")
            except (ValueError, TypeError) as e:
                # 处理不同驱动器（Windows）或无效路径的情况
                raise ParameterException(f"Invalid path configuration: {e}")
            save_path_obj = target_path
        else:
            # 仅文件名语义：强制仅使用纯文件名，防注入路径分隔符
            safe_name = Path(filename).name
            if not safe_name:
                safe_name = "attachment"
            save_path_obj = Path(safe_name).resolve()
            # 写入当前目录下文件，防止注入相对路径
            current_dir = Path.cwd().resolve()
            # 使用 os.path.commonpath() 再次校验越界（必须在当前目录或其子目录）
            save_path_parent = save_path_obj.parent
            try:
                common = os.path.commonpath([str(current_dir), str(save_path_parent)])
                if common != str(current_dir):
                    # 若 resolve 后不在当前目录，强制放到当前目录
                    save_path_obj = current_dir / safe_name
            except (ValueError, TypeError):
                # 处理不同驱动器或无效路径的情况，强制放到当前目录
                save_path_obj = current_dir / safe_name
        
        # 下载文件
        try:
            downloaded_path = await self._adownload_file(url, str(save_path_obj), status_callback=self.status_callback)
            return downloaded_path
        except Exception as e:
            raise AttachmentException(f"Failed to download attachment: {str(e)}")
    
    async def adownload_from_url(self, url: str, save_path: Optional[str] = None) -> str:
        """
        从URL下载附件（异步）
        
        Args:
            url: 附件URL
            save_path: 保存路径
            
        Returns:
            下载文件的本地路径
        """
        return await self.adownload(url, save_path)
    
    # 内部API调用方法
    async def _aupload_file(self, file_path: str, status_callback: Optional[Callable[[str], Awaitable[None]]] = None) -> Dict[str, Any]:
        """上传文件的内部API调用"""
        endpoint = f"datasheets/{self._datasheet._dst_id}/attachments"
        
        # 准备文件数据
        return await self._async_upload_file(endpoint, file_path, status_callback=status_callback)
    
    async def _async_upload_file(self, endpoint: str, file_path: str, status_callback: Optional[Callable[[str], Awaitable[None]]] = None) -> Dict[str, Any]:
        """异步上传文件"""
        file_path_obj = Path(file_path)
        filename = file_path_obj.name
        
        if status_callback:
            await status_callback(f"正在上传文件: {filename}...")
        
        # 使用 apitable 实例的 api_base 构建 URL
        base_url = self._datasheet._apitable.api_base
        # 改为标准化 URL 拼接
        if '/fusion/v1' not in base_url:
            base = base_url.rstrip('/') + '/fusion/v1/'
        else:
            base = base_url.rstrip('/') + '/'
        url = urljoin(base, endpoint.lstrip('/'))
        
        headers = {
            'Authorization': f'Bearer {self._datasheet._apitable.token}'
        }
        
        # 创建FormData并在文件打开期间发送请求（避免阻塞事件循环）
        async with aiohttp.ClientSession() as session:
            form_data = aiohttp.FormData()
            # 使用 to_thread 包装同步 open，降低在事件循环内的阻塞风险
            f = await asyncio.to_thread(open, str(file_path_obj), 'rb')
            try:
                form_data.add_field(
                    'file',
                    f,
                    filename=filename,
                    content_type='application/octet-stream'
                )
                async with session.post(url, headers=headers, data=form_data) as response:
                    # 处理响应
                    text_content = await response.text()
                    try:
                        import json
                        response_data = json.loads(text_content)
                    except json.JSONDecodeError:
                        response_data = {'message': text_content, 'success': False}
                    # 检查状态码
                    if response.status >= 400:
                        from ..exceptions import create_exception_from_response
                        raise create_exception_from_response(response_data, response.status)
                    if status_callback:
                        await status_callback(f"文件 {filename} 上传成功。")
                    return response_data
            finally:
                # 确保文件句柄被关闭，避免资源泄漏
                try:
                    f.close()
                except Exception:
                    pass
    
    async def _adownload_file(self, url: str, save_path: str, status_callback: Optional[Callable[[str], Awaitable[None]]] = None) -> str:
        """下载文件的内部实现"""
        return await self._async_download_file(url, save_path, status_callback=status_callback)
    
    async def _async_download_file(self, url: str, save_path: str, status_callback: Optional[Callable[[str], Awaitable[None]]] = None) -> str:
        """异步下载文件（流式分块写入，避免大内存占用与阻塞事件循环）"""
        import aiohttp

        if status_callback:
            await status_callback(f"正在从 {url} 下载文件...")

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise AttachmentException(f"Failed to download file: HTTP {response.status}")

                # 确保目录存在
                save_path_obj = Path(save_path)
                save_path_obj.parent.mkdir(parents=True, exist_ok=True)

                # 以流式方式写入，分块到磁盘，避免一次性读入内存
                f = await asyncio.to_thread(open, str(save_path_obj), 'wb')
                try:
                    async for chunk in response.content.iter_chunked(DOWNLOAD_CHUNK_SIZE):
                        if not chunk:
                            continue
                        # 将写入操作放到线程池，避免阻塞事件循环
                        await asyncio.to_thread(f.write, chunk)
                finally:
                    try:
                        await asyncio.to_thread(f.flush)
                    except Exception:
                        pass
                    try:
                        f.close()
                    except Exception:
                        pass

                if status_callback:
                    await status_callback(f"文件已成功下载到: {save_path_obj}")

                return str(save_path_obj)
    
    def __str__(self) -> str:
        return f"AttachmentManager({self._datasheet})"
    
    def __repr__(self) -> str:
        return f"AttachmentManager(datasheet={self._datasheet._dst_id})"


__all__ = ['Attachment', 'AttachmentManager']
