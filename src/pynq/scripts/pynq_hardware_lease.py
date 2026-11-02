"""Serialize cooperating board tools across notebook kernels and processes."""
from functools import wraps
import os
import sys
import threading

_mutex=threading.Lock()
_local=threading.local()
_retained=[]


def quarantined():
    return bool(getattr(sys.modules.get('pynq_blackbox'),'QUARANTINED_BUFFERS',[]))


def _release(descriptor):
    if descriptor is not None:
        import fcntl
        fcntl.flock(descriptor,fcntl.LOCK_UN);os.close(descriptor)
    _mutex.release()


class HardwareLease:
    def __enter__(self):
        self.nested=getattr(_local,'depth',0)>0
        self.descriptor=None
        if not self.nested:
            if not _mutex.acquire(False):raise RuntimeError('板卡正由另一采集任务使用，请等待其完成')
            try:
                if os.name=='posix':
                    import fcntl
                    self.descriptor=os.open('/run/lock/signal_blackbox.lock',os.O_CREAT|os.O_RDWR,0o600)
                    fcntl.flock(self.descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    os.ftruncate(self.descriptor,0);os.write(self.descriptor,str(os.getpid()).encode('ascii'))
            except BaseException as exc:
                if self.descriptor is not None:os.close(self.descriptor)
                _mutex.release()
                raise RuntimeError('板卡正由另一进程使用或无法取得硬件锁: '+str(exc))
        _local.depth=getattr(_local,'depth',0)+1
        return self

    def __exit__(self,*exception):
        _local.depth-=1
        if not self.nested:
            if quarantined():_retained.append(self.descriptor)
            else:_release(self.descriptor)


def release_quarantine_leases():
    if quarantined():raise RuntimeError('DMA缓冲区仍被保留，不能释放硬件锁')
    while _retained:_release(_retained.pop())


def serialized_hardware(function):
    @wraps(function)
    def locked(*args,**kwargs):
        with HardwareLease():return function(*args,**kwargs)
    return locked
