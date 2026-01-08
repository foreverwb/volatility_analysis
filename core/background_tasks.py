"""
后台任务管理模块 - v2.6.0
Background Task Manager for IV Fetching

功能：
1. 管理 IV 获取后台任务
2. 任务状态跟踪
3. 完成后回调通知
"""
import threading
import time
import uuid
from typing import Dict, List, Callable, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"      # 等待中
    RUNNING = "running"      # 执行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 失败


@dataclass
class BackgroundTask:
    """后台任务"""
    task_id: str
    task_type: str  # "iv_fetch", "oi_fetch" 等
    symbols: List[str]
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: int = 0  # 0-100
    total_symbols: int = 0
    completed_symbols: int = 0
    result: Optional[Dict] = None
    error: Optional[str] = None
    callback: Optional[Callable] = None  # 完成后的回调函数
    
    def to_dict(self) -> Dict:
        """转换为字典（用于序列化）"""
        return {
            'task_id': self.task_id,
            'task_type': self.task_type,
            'status': self.status.value,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'progress': self.progress,
            'total_symbols': self.total_symbols,
            'completed_symbols': self.completed_symbols,
            'symbols': self.symbols,
            'error': self.error
        }


class BackgroundTaskManager:
    """后台任务管理器（单例）"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.tasks: Dict[str, BackgroundTask] = {}
        self.task_lock = threading.Lock()
        self._initialized = True
        
        print("✓ BackgroundTaskManager initialized")
    
    def create_task(
        self,
        task_type: str,
        symbols: List[str],
        callback: Optional[Callable] = None
    ) -> str:
        """
        创建后台任务
        
        Args:
            task_type: 任务类型
            symbols: 标的列表
            callback: 完成后的回调函数
            
        Returns:
            task_id
        """
        task_id = str(uuid.uuid4())
        
        task = BackgroundTask(
            task_id=task_id,
            task_type=task_type,
            symbols=symbols,
            total_symbols=len(symbols),
            callback=callback
        )
        
        with self.task_lock:
            self.tasks[task_id] = task
        
        print(f"✓ Task created: {task_id} ({task_type}, {len(symbols)} symbols)")
        
        return task_id
    
    def get_task(self, task_id: str) -> Optional[BackgroundTask]:
        """获取任务信息"""
        with self.task_lock:
            return self.tasks.get(task_id)
    
    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        progress: Optional[int] = None,
        completed_symbols: Optional[int] = None,
        result: Optional[Dict] = None,
        error: Optional[str] = None
    ):
        """更新任务状态"""
        with self.task_lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            
            task.status = status
            
            if progress is not None:
                task.progress = progress
            
            if completed_symbols is not None:
                task.completed_symbols = completed_symbols
            
            if result is not None:
                task.result = result
            
            if error is not None:
                task.error = error
            
            if status == TaskStatus.RUNNING and task.started_at is None:
                task.started_at = datetime.now()
            
            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                task.completed_at = datetime.now()
    
    def execute_task_async(
        self,
        task_id: str,
        func: Callable,
        *args,
        **kwargs
    ):
        """
        在后台线程中执行任务
        
        Args:
            task_id: 任务ID
            func: 要执行的函数
            *args, **kwargs: 函数参数
        """
        def _run():
            task = self.get_task(task_id)
            if not task:
                return
            
            try:
                print(f"▶ Task {task_id} started")
                self.update_task_status(task_id, TaskStatus.RUNNING)
                
                # 执行任务
                result = func(*args, **kwargs)
                
                self.update_task_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    progress=100,
                    result=result
                )
                
                print(f"✓ Task {task_id} completed")
                
                # 执行回调
                if task.callback:
                    try:
                        task.callback(task_id, result)
                    except Exception as e:
                        print(f"⚠ Task callback failed: {e}")
            
            except Exception as e:
                print(f"✗ Task {task_id} failed: {e}")
                self.update_task_status(
                    task_id,
                    TaskStatus.FAILED,
                    error=str(e)
                )
        
        # 启动后台线程
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
    
    def get_all_tasks(self) -> List[BackgroundTask]:
        """获取所有任务"""
        with self.task_lock:
            return list(self.tasks.values())
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """清理旧任务"""
        now = datetime.now()
        with self.task_lock:
            to_remove = []
            for task_id, task in self.tasks.items():
                if task.completed_at:
                    age = (now - task.completed_at).total_seconds() / 3600
                    if age > max_age_hours:
                        to_remove.append(task_id)
            
            for task_id in to_remove:
                del self.tasks[task_id]
            
            if to_remove:
                print(f"✓ Cleaned up {len(to_remove)} old tasks")


# 全局单例
_manager = None

def get_task_manager() -> BackgroundTaskManager:
    """获取全局任务管理器"""
    global _manager
    if _manager is None:
        _manager = BackgroundTaskManager()
    return _manager


# ========== IV 获取专用任务函数 ==========

def create_iv_fetch_task(
    symbols: List[str],
    on_complete: Optional[Callable] = None
) -> str:
    """
    创建 IV 获取后台任务
    
    Args:
        symbols: 标的列表
        on_complete: 完成回调函数 (task_id, result)
        
    Returns:
        task_id
    """
    manager = get_task_manager()
    task_id = manager.create_task(
        task_type="iv_fetch",
        symbols=symbols,
        callback=on_complete
    )
    return task_id


def execute_iv_fetch_task(task_id: str, symbols: List[str]):
    """
    执行 IV 获取任务（在后台线程中运行）
    
    Args:
        task_id: 任务ID
        symbols: 标的列表
    """
    from core.futu_option_iv import fetch_iv_term_structure
    
    manager = get_task_manager()
    
    # 进度回调
    def progress_callback(completed, total, symbol):
        progress = int((completed / total) * 100)
        manager.update_task_status(
            task_id,
            TaskStatus.RUNNING,
            progress=progress,
            completed_symbols=completed
        )
    
    # 执行获取
    def _fetch():
        return fetch_iv_term_structure(
            symbols,
            max_workers=3,
            progress_callback=progress_callback
        )
    
    manager.execute_task_async(task_id, _fetch)
